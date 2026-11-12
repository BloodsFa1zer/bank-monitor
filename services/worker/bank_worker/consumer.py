"""One consumer = one thread with its own PostgreSQL and RabbitMQ connections.

pika's BlockingConnection is not thread-safe, so nothing here is shared between
threads except the metrics and the stop event.
"""

import contextlib
import logging
import threading
import time
from datetime import UTC, datetime

import psycopg
from pika.exceptions import AMQPError

from bank_worker import metrics
from bank_worker.processor import Outcome, UnknownAccount, process_transfer
from bank_worker.settings import SettingsCache
from bankmon_common import amqp, db
from bankmon_common.logging import log_event
from bankmon_common.messages import InvalidMessage, TransferRequested, decode

logger = logging.getLogger(__name__)


class DatabaseUnavailable(Exception):
    """The PostgreSQL connection broke while a message was being processed."""


class Consumer(threading.Thread):
    def __init__(self, index: int, database_url: str, amqp_url: str, stopping: threading.Event):
        # Daemon: a thread stuck reconnecting must not keep the process alive on shutdown.
        super().__init__(name=f"consumer-{index}", daemon=True)
        self._database_url = database_url
        self._amqp_url = amqp_url
        self._stopping = stopping
        self._db: psycopg.Connection | None = None
        self._settings: SettingsCache | None = None
        self._connection = None
        self._channel = None

    # --- lifecycle ------------------------------------------------------------

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._connect()
                if not self._stopping.is_set():
                    self._channel.start_consuming()
            except DatabaseUnavailable as exc:
                self._connection_lost("postgres", exc.__cause__)
            except AMQPError as exc:
                self._connection_lost("rabbitmq", exc)
            except Exception:
                logger.exception("Consumer failed unexpectedly, reconnecting")
            finally:
                self._close()
            # Unacknowledged messages went back to the queue; reconnect after a pause.
            self._stopping.wait(1.0)

    def request_stop(self) -> None:
        """Called from the main thread on SIGTERM: finish the current message, then stop."""
        connection = self._connection
        if connection is not None and connection.is_open:
            with contextlib.suppress(Exception):
                connection.add_callback_threadsafe(self._stop_consuming)

    def _stop_consuming(self) -> None:
        if self._channel is not None and self._channel.is_open:
            self._channel.stop_consuming()

    def _connect(self) -> None:
        self._db = db.connect(self._database_url, application_name="bank-worker", autocommit=True)
        self._settings = SettingsCache(self._db)
        self._connection = amqp.connect(self._amqp_url)
        self._channel = self._connection.channel()
        amqp.declare_topology(self._channel)
        self._channel.basic_qos(prefetch_count=1)
        self._channel.basic_consume(amqp.TRANSFERS_QUEUE, on_message_callback=self._on_message)

    def _close(self) -> None:
        if self._connection is not None and self._connection.is_open:
            with contextlib.suppress(Exception):
                self._connection.close()
        if self._db is not None:
            self._db.close()
        self._connection = self._channel = self._db = self._settings = None

    def _connection_lost(self, target: str, exc: BaseException | None) -> None:
        if self._stopping.is_set():
            return
        log_event(
            logger,
            "warning",
            "connection_lost",
            f"Lost connection to {target}, reconnecting",
            target=target,
            error=repr(exc),
        )

    # --- messages -------------------------------------------------------------

    def _on_message(self, channel, method, properties, body: bytes) -> None:
        with metrics.IN_FLIGHT.track_inprogress():
            try:
                msg = decode(body)
                started = time.monotonic()
                outcome = process_transfer(self._db, msg, self._settings.get)
            except (InvalidMessage, UnknownAccount) as exc:
                self._reject(channel, method, str(exc))
                return
            except psycopg.Error as exc:
                if self._db.closed or self._db.broken:
                    # No ack: the message returns to the queue when the channel closes.
                    raise DatabaseUnavailable from exc
                sqlstate = exc.sqlstate or "unknown"
                metrics.DB_ERRORS.labels(sqlstate=sqlstate).inc()
                log_event(
                    logger,
                    "error",
                    "db_error",
                    f"Database error {sqlstate}, message rejected",
                    sqlstate=sqlstate,
                    error=str(exc).strip(),
                )
                self._reject(channel, method, f"database error {sqlstate}")
                return
            except Exception as exc:
                self._reject(channel, method, f"unexpected error: {exc!r}", exc_info=True)
                return
            channel.basic_ack(method.delivery_tag)
            self._record(msg, outcome, time.monotonic() - started)

    def _reject(self, channel, method, reason: str, exc_info: bool = False) -> None:
        channel.basic_reject(method.delivery_tag, requeue=False)
        metrics.DEAD_LETTERED.inc()
        log_event(
            logger,
            "error",
            "message_rejected",
            f"Message sent to the dead-letter queue: {reason}",
            reason=reason,
            exc_info=exc_info,
        )

    def _record(self, msg: TransferRequested, outcome: Outcome, elapsed: float) -> None:
        if outcome.status == "duplicate":
            metrics.DUPLICATES.inc()
            logger.info("Transfer %s was already recorded, message acknowledged", msg.transfer_id)
            return
        metrics.TRANSFERS_PROCESSED.labels(
            status=outcome.status, reason=outcome.reason or "none"
        ).inc()
        metrics.PROCESSING_SECONDS.labels(status=outcome.status).observe(elapsed)
        waited = (datetime.now(UTC) - msg.requested_at).total_seconds()
        metrics.E2E_SECONDS.observe(max(0.0, waited))
        fields = {
            "transfer_id": str(msg.transfer_id),
            "from_account": msg.from_account,
            "to_account": msg.to_account,
            "amount": f"{msg.amount:.2f}",
            "attempts": outcome.attempts,
            "duration_ms": round(elapsed * 1000, 1),
        }
        if outcome.status == "completed":
            log_event(logger, "info", "transfer_completed", "Transfer completed", **fields)
        else:
            log_event(
                logger,
                "warning",
                "transfer_failed",
                f"Transfer failed: {outcome.reason}",
                reason=outcome.reason,
                **fields,
            )
