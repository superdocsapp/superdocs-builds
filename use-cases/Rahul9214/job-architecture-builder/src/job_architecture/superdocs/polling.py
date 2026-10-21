"""Bounded polling for SuperDocs async jobs.

Long processing is expected. Timeout means we stopped waiting, not that SuperDocs failed.
"""

from __future__ import annotations

import time
from typing import Callable

from job_architecture.superdocs.errors import JobFailedError, JobTimeoutError
from job_architecture.superdocs.models import JobSnapshot

SleepFn = Callable[[float], None]
ClockFn = Callable[[], float]

TERMINAL = frozenset({"completed", "failed", "cancelled"})
REVIEW = frozenset({"awaiting_approval"})


def wait_for_job(
    fetch: Callable[[], JobSnapshot],
    *,
    poll_interval_seconds: float,
    max_wait_seconds: float,
    stop_on_review: bool = True,
    sleep: SleepFn | None = None,
    clock: ClockFn | None = None,
) -> JobSnapshot:
    sleeper = sleep or time.sleep
    now = clock or time.monotonic
    deadline = now() + max_wait_seconds
    snapshot = fetch()
    while True:
        if snapshot.status in TERMINAL:
            if snapshot.status == "failed":
                raise JobFailedError(
                    snapshot.error or "SuperDocs job failed",
                    cause=snapshot.error,
                )
            return snapshot
        if stop_on_review and snapshot.status in REVIEW:
            return snapshot
        remaining = deadline - now()
        if remaining <= 0:
            raise JobTimeoutError(
                f"SuperDocs job {snapshot.job_id} still {snapshot.status} "
                f"after {max_wait_seconds:.0f}s; it may still be running"
            )
        sleeper(min(poll_interval_seconds, remaining))
        snapshot = fetch()
