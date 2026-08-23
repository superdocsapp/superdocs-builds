"""Exponential-backoff retry for transient SuperDocs failures.

The task doc itself warns that SuperDocs operations "can take from thirty
seconds to several minutes with no visible progress" -- that's the shape
of a real integration hitting transient slowness or a dropped connection,
not necessarily a hard failure. Retrying a bounded number of times before
giving up on a stage is the difference between a build that survives a
flaky network and one that only survives the demo.

Retryability is judged primarily from the real HTTP status code carried
on SuperDocsAPIError (RealSuperDocsClient._raise_for_status sets this
from the actual response), the same way a production HTTP client would
treat 429/5xx as transient and 4xx (other than 429) as not worth
retrying. When no status code is available -- the fake client's
simulated failures, or a network-level error that never got a response
at all -- we fall back to a message-substring heuristic as a reasonable
approximation.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from app.clients.superdocs_client import SuperDocsAPIError

T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY_SECONDS = 0.05

# Fallback substrings used only when no status code is available (the
# fake client's simulated outages, or a raw network error that never
# reached a server to get a status code from).
_RETRYABLE_MARKERS = ("outage", "timeout", "unavailable", "connection")


def is_retryable(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        # 429 (rate limited) and any 5xx (server-side/transient) are
        # worth retrying; every other 4xx means the request itself is
        # the problem and a retry won't fix it.
        return status_code == 429 or status_code >= 500
    message = str(error).lower()
    return any(marker in message for marker in _RETRYABLE_MARKERS)


@dataclass
class RetryResult:
    value: object
    attempts: int


def call_with_retry(
    fn: Callable[[], T],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> RetryResult:
    """Calls fn(), retrying on retryable SuperDocsAPIError with
    exponential backoff (base_delay * 2**attempt). Raises the last error
    if every attempt is exhausted, or immediately if the error isn't
    judged retryable. Returns both the value and how many attempts it
    actually took, so callers can report retry counts honestly instead
    of hiding them."""
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            value = fn()
            return RetryResult(value=value, attempts=attempt)
        except SuperDocsAPIError as e:
            last_error = e
            e.attempts = attempt  # type: ignore[attr-defined]
            if not is_retryable(e) or attempt == max_attempts:
                raise
            sleep_fn(base_delay * (2 ** (attempt - 1)))
    # unreachable, but keeps type-checkers happy
    raise last_error  # type: ignore[misc]


class CircuitOpenError(Exception):
    """Raised instead of calling SuperDocs at all while the breaker is
    open. Distinct from SuperDocsAPIError so callers (and tests) can
    tell "we tried and it failed" apart from "we didn't even try
    because the last N calls all failed"."""


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float = 0.0
    is_open: bool = False


class CircuitBreaker:
    """Per-tenant breaker shared across every stage's SuperDocs call.

    Per-file retry (call_with_retry above) handles one file hitting one
    transient blip. It does not help when SuperDocs itself is down: every
    file arriving during an outage still burns its own full retry budget
    against a service that isn't coming back in the next few hundred ms,
    which just multiplies load on an already-struggling dependency and
    slows every concurrent run down together.

    This breaker trips after `failure_threshold` consecutive retryable
    failures (tracked across calls, not within one call's own retries)
    and then fails fast -- raising CircuitOpenError without attempting a
    network call at all -- for `reset_after_seconds`, after which it
    allows exactly one trial call through (half-open); success closes
    the breaker and resets the failure count, another failure re-opens
    it and restarts the timer. A single successful call at any time
    resets the failure count to zero.

    Thread-safe: shared across concurrent stage calls within a tenant.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_after_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_after_seconds = reset_after_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state = _CircuitState()

    def _half_open_allowed(self) -> bool:
        return (self._clock() - self._state.opened_at) >= self.reset_after_seconds

    def before_call(self) -> None:
        with self._lock:
            if self._state.is_open and not self._half_open_allowed():
                raise CircuitOpenError(
                    f"circuit open after {self._state.failures} consecutive "
                    f"failures; retrying in "
                    f"{self.reset_after_seconds - (self._clock() - self._state.opened_at):.1f}s"
                )

    def record_success(self) -> None:
        with self._lock:
            self._state = _CircuitState()

    def record_failure(self) -> None:
        with self._lock:
            self._state.failures += 1
            if self._state.failures >= self.failure_threshold:
                self._state.is_open = True
                self._state.opened_at = self._clock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._state.is_open and not self._half_open_allowed()

    def call(self, fn: Callable[[], T]) -> T:
        """Convenience wrapper: check-call-record in one place."""
        self.before_call()
        try:
            value = fn()
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()
            return value
