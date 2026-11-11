"""Helpers for e2e tests. Each stage adds its own; reuse before writing new ones.

Waiting is done only by polling with a timeout (rule R12): this module is the
only place in tests/ where time.sleep is allowed.
"""

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import psycopg


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
