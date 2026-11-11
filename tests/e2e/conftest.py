"""Shared fixtures for e2e tests.

The tests run inside the `tests` container on the compose network and talk to
services by their names. Each stage adds the readiness checks it needs here.
"""

import pytest

from .helpers import db, wait_until


def _postgres_accepts_app() -> bool:
    with db("app") as conn:
        return conn.execute("SELECT 1").fetchone() == (1,)


@pytest.fixture(scope="session", autouse=True)
def stack_ready() -> None:
    """Wait until the stack can serve the tests (after `make up` or a restart)."""
    wait_until(_postgres_accepts_app, timeout=180, interval=1, desc="PostgreSQL to accept bank_app")
