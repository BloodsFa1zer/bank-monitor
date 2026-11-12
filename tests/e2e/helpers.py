"""Helpers for e2e tests. Each stage adds its own; reuse before writing new ones.

Waiting is done only by polling with a timeout (rule R12): this module is the
only place in tests/ where time.sleep is allowed.
"""

import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pika
import psycopg
import requests
from prometheus_client.parser import text_string_to_metric_families
from psycopg.rows import dict_row

from bankmon_common import amqp
from bankmon_common.messages import TransferRequested

WORKER_URL = os.environ.get("WORKER_URL", "http://worker:8000")


def wait_until[T](
    fn: Callable[[], T], timeout: float = 30.0, interval: float = 0.5, desc: str = ""
) -> T:
    """Call ``fn`` until it returns a truthy value and return that value.

    Exceptions raised by ``fn`` count as "not yet". After ``timeout`` seconds an
    AssertionError reports ``desc`` and the last value or exception.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = fn()
            last = f"last value: {value!r}"
            if value:
                return value
        except Exception as exc:  # any failure means "not ready yet"
            last = f"last error: {exc!r}"
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {desc or fn}; {last}")
        time.sleep(interval)


# --- PostgreSQL (S1) ---------------------------------------------------------

_DSN_ENV = {"admin": "PG_ADMIN_DSN", "app": "PG_APP_DSN", "monitor": "PG_MONITOR_DSN"}


@contextmanager
def db(role: str = "admin") -> Iterator[psycopg.Connection]:
    """Connection to the bank database as "admin", "app" or "monitor".

    Nothing is saved unless the test calls ``conn.commit()``: closing the
    connection rolls back the open transaction.
    """
    conn = psycopg.connect(
        os.environ[_DSN_ENV[role]], connect_timeout=5, application_name="e2e-tests"
    )
    try:
        yield conn
    finally:
        conn.close()


# Invariants I1–I4 of §6.4. Each query returns the offending rows (at most 5).
_INVARIANTS = {
    "I1 balance equals the sum of its ledger entries": """
        SELECT a.id, a.balance, COALESCE(l.total, 0) AS ledger_total
        FROM accounts a
        LEFT JOIN (SELECT account_id, SUM(delta) AS total
                   FROM ledger_entries GROUP BY account_id) l ON l.account_id = a.id
        WHERE a.balance <> COALESCE(l.total, 0)
        ORDER BY a.id LIMIT 5""",
    "I2 transfer entries sum to zero": """
        SELECT total
        FROM (SELECT COALESCE(SUM(delta), 0) AS total FROM ledger_entries
              WHERE kind IN ('transfer_in', 'transfer_out')) s
        WHERE total <> 0""",
    "I3 no negative balances": """
        SELECT id, balance FROM accounts WHERE balance < 0 ORDER BY id LIMIT 5""",
    "I4 ledger entries match the transfer status": """
        SELECT t.id, t.status, count(e.id) AS entries
        FROM transfers t
        LEFT JOIN ledger_entries e ON e.transfer_id = t.id
        GROUP BY t.id
        HAVING NOT (
            (t.status = 'completed'
             AND count(e.id) = 2
             AND count(*) FILTER (WHERE e.kind = 'transfer_out'
                                    AND e.account_id = t.from_account
                                    AND e.delta = -t.amount) = 1
             AND count(*) FILTER (WHERE e.kind = 'transfer_in'
                                    AND e.account_id = t.to_account
                                    AND e.delta = t.amount) = 1)
            OR (t.status = 'failed' AND count(e.id) = 0))
        LIMIT 5""",
}


def check_invariants(conn: psycopg.Connection | None = None) -> list[str]:
    """Check I1–I4 on one consistent snapshot; return the violations ([] means all hold).

    Without ``conn`` a fresh REPEATABLE READ connection is used, so transfers that
    commit while the checks run cannot make them disagree with each other.
    """
    if conn is None:
        with db() as own:
            own.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            return check_invariants(own)
    violations = []
    for name, query in _INVARIANTS.items():
        rows = conn.execute(query).fetchall()
        if rows:
            violations.append(f"{name}: {rows}")
    return violations


# --- RabbitMQ and the worker (S2) --------------------------------------------


@contextmanager
def amqp_channel() -> Iterator[pika.adapters.blocking_connection.BlockingChannel]:
    """A channel with publisher confirms: basic_publish returns once the broker has the message."""
    connection = pika.BlockingConnection(pika.URLParameters(os.environ["AMQP_URL"]))
    try:
        channel = connection.channel()
        channel.confirm_delivery()
        yield channel
    finally:
        if connection.is_open:
            connection.close()


def make_transfer(
    from_account: int,
    to_account: int,
    amount: Decimal | str,
    *,
    transfer_id: str | None = None,
    scenario: str = "normal",
) -> TransferRequested:
    return TransferRequested(
        transfer_id=uuid.UUID(transfer_id) if transfer_id else uuid.uuid4(),
        from_account=from_account,
        to_account=to_account,
        amount=Decimal(amount),
        requested_at=datetime.now(UTC),
        scenario=scenario,
    )


def publish_raw(body: bytes, *, channel=None) -> None:
    """Publish any body to the transfers exchange, the way the generator does."""
    if channel is None:
        with amqp_channel() as own:
            publish_raw(body, channel=own)
        return
    channel.basic_publish(
        exchange=amqp.TRANSFERS_EXCHANGE,
        routing_key=amqp.TRANSFER_ROUTING_KEY,
        body=body,
        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
        mandatory=True,
    )


def publish_transfer(
    from_account: int,
    to_account: int,
    amount: Decimal | str,
    *,
    transfer_id: str | None = None,
    scenario: str = "normal",
    channel=None,
) -> str:
    """Publish a valid TransferRequested; return its transfer_id."""
    msg = make_transfer(
        from_account, to_account, amount, transfer_id=transfer_id, scenario=scenario
    )
    publish_raw(msg.encode(), channel=channel)
    return str(msg.transfer_id)


def transfer_row(transfer_id: str) -> dict | None:
    with db() as conn:
        conn.row_factory = dict_row
        return conn.execute("SELECT * FROM transfers WHERE id = %s", (transfer_id,)).fetchone()


def wait_transfer(transfer_id: str, timeout: float = 10) -> dict:
    """Wait until the worker has recorded the transfer; return its row."""
    return wait_until(
        lambda: transfer_row(transfer_id),
        timeout=timeout,
        interval=0.2,
        desc=f"transfer {transfer_id}",
    )


def ledger_entries(transfer_id: str) -> list[dict]:
    with db() as conn:
        conn.row_factory = dict_row
        return conn.execute(
            "SELECT * FROM ledger_entries WHERE transfer_id = %s ORDER BY kind", (transfer_id,)
        ).fetchall()


def latency_s(transfer_id: str, timeout: float = 15) -> float:
    """Seconds between requested_at and processed_at of a transfer (waits for it)."""
    row = wait_transfer(transfer_id, timeout=timeout)
    return (row["processed_at"] - row["requested_at"]).total_seconds()


def rabbitmq_api(path: str) -> dict:
    """GET from the RabbitMQ management API. Its statistics lag by up to 5 s."""
    response = requests.get(
        f"{os.environ['RABBITMQ_API']}/api/{path}",
        auth=(os.environ["RABBITMQ_DEFAULT_USER"], os.environ["RABBITMQ_DEFAULT_PASS"]),
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def queue_info(name: str) -> dict:
    return rabbitmq_api(f"queues/%2F/{name}")


def queue_counts(name: str) -> tuple[int, int]:
    """(messages ready, consumers) of a queue, live from the broker (no statistics lag)."""
    with amqp_channel() as channel:
        method = channel.queue_declare(queue=name, passive=True).method
        return method.message_count, method.consumer_count


def wait_queue_drained(timeout: float = 60) -> None:
    wait_until(
        lambda: queue_counts(amqp.TRANSFERS_QUEUE)[0] == 0,
        timeout=timeout,
        desc="no messages waiting in transfers.requested",
    )


def drain_queue(name: str) -> list[bytes]:
    """Take (and acknowledge) every message waiting in a queue; return their bodies."""
    bodies = []
    with amqp_channel() as channel:
        while True:
            method, _properties, body = channel.basic_get(queue=name)
            if method is None:
                return bodies
            channel.basic_ack(method.delivery_tag)
            bodies.append(body)


def metric_value(url: str, name: str, labels: dict[str, str] | None = None) -> float:
    """Sum of the samples called ``name`` whose labels include ``labels``; 0 if none."""
    text = requests.get(f"{url}/metrics", timeout=5).text
    total = 0.0
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name and all(
                sample.labels.get(key) == value for key, value in (labels or {}).items()
            ):
                total += sample.value
    return total


def metric_families(url: str) -> set[str]:
    """Names of the metric families an endpoint exposes (counters without `_total`)."""
    text = requests.get(f"{url}/metrics", timeout=5).text
    return {family.name for family in text_string_to_metric_families(text)}


def _set_scenario_state(
    lock_order: str, lock_gap_ms: int, sleep_ms: int, scenario: str | None = None
) -> None:
    with db() as conn:
        conn.execute(
            """UPDATE scenario_state
               SET scenario = COALESCE(%s::text, scenario), lock_order = %s,
                   lock_gap_ms = %s, sleep_ms = %s, updated_at = now()
               WHERE id = 1""",
            (scenario, lock_order, lock_gap_ms, sleep_ms),
        )
        conn.commit()


@contextmanager
def worker_settings(lock_order: str, lock_gap_ms: int, sleep_ms: int) -> Iterator[None]:
    """Change what the worker applies (it re-reads scenario_state within 1 s).

    On exit the row always goes back to the values of the `normal` scenario.
    """
    _set_scenario_state(lock_order, lock_gap_ms, sleep_ms)
    try:
        yield
    finally:
        _set_scenario_state("sorted", 0, 0, scenario="normal")
