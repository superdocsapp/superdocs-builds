"""Tests for webapp/jobs.py -- the background job queue backing the
webapp's real-run drafting path."""
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).parent.parent / "webapp"))

from jobs import JobRunner, JobStore, STATUS_COMPLETED, STATUS_FAILED, STATUS_PENDING  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite3'}", connect_args={"check_same_thread": False})


def test_create_starts_in_pending_status(engine):
    store = JobStore(engine)
    job_id = store.create(case_id="CASE-1")
    job = store.get(job_id)
    assert job.status == STATUS_PENDING
    assert job.case_id == "CASE-1"
    assert job.review_id is None


def test_mark_completed_records_review_id(engine):
    store = JobStore(engine)
    job_id = store.create()
    store.mark_running(job_id)
    store.mark_completed(job_id, "review-abc")
    job = store.get(job_id)
    assert job.status == STATUS_COMPLETED
    assert job.review_id == "review-abc"


def test_mark_failed_records_error(engine):
    store = JobStore(engine)
    job_id = store.create()
    store.mark_failed(job_id, "boom")
    job = store.get(job_id)
    assert job.status == STATUS_FAILED
    assert job.error == "boom"


def test_get_missing_job_returns_none(engine):
    store = JobStore(engine)
    assert store.get("does-not-exist") is None


def test_job_runner_runs_function_in_background_and_marks_completed(engine):
    store = JobStore(engine)
    runner = JobRunner(store, max_workers=1)
    job_id = store.create()

    runner.submit(job_id, lambda: "review-xyz")

    deadline = time.monotonic() + 2.0
    job = store.get(job_id)
    while job.status not in (STATUS_COMPLETED, STATUS_FAILED) and time.monotonic() < deadline:
        time.sleep(0.01)
        job = store.get(job_id)

    assert job.status == STATUS_COMPLETED
    assert job.review_id == "review-xyz"


def test_job_runner_marks_failed_on_exception_without_raising(engine):
    store = JobStore(engine)
    runner = JobRunner(store, max_workers=1)
    job_id = store.create()

    def _boom():
        raise RuntimeError("simulated SuperDocs failure")

    runner.submit(job_id, _boom)  # must not raise here -- failure surfaces via job status

    deadline = time.monotonic() + 2.0
    job = store.get(job_id)
    while job.status not in (STATUS_COMPLETED, STATUS_FAILED) and time.monotonic() < deadline:
        time.sleep(0.01)
        job = store.get(job_id)

    assert job.status == STATUS_FAILED
    assert "simulated SuperDocs failure" in job.error


def test_prune_stale_removes_old_jobs(engine):
    store = JobStore(engine, ttl_s=0)
    job_id = store.create()
    time.sleep(0.01)
    store.prune_stale()
    assert store.get(job_id) is None
