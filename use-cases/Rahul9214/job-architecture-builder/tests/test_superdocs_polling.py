"""Polling helper tests with injected clock/sleep."""

from __future__ import annotations

import pytest

from job_architecture.superdocs.errors import JobFailedError, JobTimeoutError
from job_architecture.superdocs.models import JobSnapshot
from job_architecture.superdocs.polling import wait_for_job


def _snap(status: str, progress: int = 0) -> JobSnapshot:
    return JobSnapshot(
        job_id="job_1",
        session_id="sess",
        raw_status=status if status != "queued" else "pending",
        status=status,
        progress=progress,
        error="boom" if status == "failed" else None,
        pending_changes=(),
        awaiting_kind=None,
        result=None,
        metadata={},
        raw={"status": status},
    )


def test_wait_stops_on_review():
    states = [_snap("queued"), _snap("processing", 40), _snap("awaiting_approval", 80)]

    def fetch() -> JobSnapshot:
        return states.pop(0)

    snapshot = wait_for_job(
        fetch,
        poll_interval_seconds=1,
        max_wait_seconds=10,
        sleep=lambda _: None,
        clock=lambda: 0.0,
    )
    assert snapshot.status == "awaiting_approval"


def test_wait_completed():
    states = [_snap("processing", 10), _snap("completed", 100)]
    snapshot = wait_for_job(
        lambda: states.pop(0),
        poll_interval_seconds=1,
        max_wait_seconds=10,
        sleep=lambda _: None,
        clock=lambda: 0.0,
    )
    assert snapshot.status == "completed"


def test_wait_failed():
    with pytest.raises(JobFailedError):
        wait_for_job(
            lambda: _snap("failed"),
            poll_interval_seconds=1,
            max_wait_seconds=10,
            sleep=lambda _: None,
            clock=lambda: 0.0,
        )


def test_wait_timeout():
    ticks = {"now": 0.0}

    def clock() -> float:
        return ticks["now"]

    def sleep(seconds: float) -> None:
        ticks["now"] += max(seconds, 0.1)

    with pytest.raises(JobTimeoutError):
        wait_for_job(
            lambda: _snap("processing", 5),
            poll_interval_seconds=1,
            max_wait_seconds=2,
            sleep=sleep,
            clock=clock,
        )
