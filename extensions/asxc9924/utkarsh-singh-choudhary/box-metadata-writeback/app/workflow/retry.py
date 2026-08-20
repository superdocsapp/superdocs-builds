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
