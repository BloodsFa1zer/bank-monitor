"""Helpers for e2e tests. Each stage adds its own; reuse before writing new ones.

Waiting is done only by polling with a timeout (rule R12): this module is the
only place in tests/ where time.sleep is allowed.
"""

import time
from collections.abc import Callable


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
