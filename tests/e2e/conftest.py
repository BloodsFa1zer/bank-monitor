"""Shared fixtures for e2e tests.

The tests run inside the `tests` container on the compose network and talk to
services by their names. Each stage adds the readiness checks it needs here.
"""

import os

import pytest
import requests

from bankmon_common import amqp

from .helpers import WORKER_URL, db, queue_counts, wait_until


def _postgres_accepts_app() -> bool:
    with db("app") as conn:
        return conn.execute("SELECT 1").fetchone() == (1,)


def _worker_consuming() -> bool:
    requests.get(f"{WORKER_URL}/metrics", timeout=3).raise_for_status()
    _ready, consumers = queue_counts(amqp.TRANSFERS_QUEUE)
    return consumers == int(os.environ["WORKER_CONCURRENCY"])


@pytest.fixture(scope="session", autouse=True)
def stack_ready() -> None:
    """Wait until the stack can serve the tests (after `make up` or a restart)."""
    wait_until(_postgres_accepts_app, timeout=180, interval=1, desc="PostgreSQL to accept bank_app")
    wait_until(_worker_consuming, timeout=180, interval=1, desc="all worker consumers to attach")
