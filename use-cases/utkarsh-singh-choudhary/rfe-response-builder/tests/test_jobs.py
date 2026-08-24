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


# --- update_progress -----------------------------------------------------------

def test_update_progress_records_completed_total_and_label(engine):
    store = JobStore(engine)
    job_id = store.create()
    store.update_progress(job_id, completed=2, total=5, current_item_label="Response to Item 3")
    job = store.get(job_id)
    assert job.items_completed == 2
    assert job.items_total == 5
    assert job.current_item_label == "Response to Item 3"


def test_update_progress_can_be_called_multiple_times(engine):
    store = JobStore(engine)
    job_id = store.create()
    store.update_progress(job_id, completed=1, total=3, current_item_label="Response to Item 1")
    store.update_progress(job_id, completed=2, total=3, current_item_label="Response to Item 2")
    job = store.get(job_id)
    assert job.items_completed == 2
    assert job.current_item_label == "Response to Item 2"


def test_new_job_has_no_progress_until_update_progress_is_called(engine):
    store = JobStore(engine)
    job_id = store.create()
    job = store.get(job_id)
    assert job.items_total is None
    assert job.items_completed is None
    assert job.current_item_label is None


# --- self-migration for pre-existing old-schema databases -----------------------

def test_jobstore_self_migrates_a_pre_existing_old_schema_database(tmp_path):
    """A genuinely pre-existing `background_jobs` table (as it looked
    before items_total/items_completed/current_item_label existed) must
    not break JobStore -- SQLAlchemy's create_all() only creates missing
    tables, it never alters an existing one, so without a real migration
    step this would fail every read/write with 'no such column'. Builds
    an actual old-schema SQLite file first (not a mock), then confirms
    JobStore can read/write it correctly after construction."""
    from sqlalchemy import Column, Float, MetaData, String, Table

    db_path = tmp_path / "old_schema.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    old_metadata = MetaData()
    Table(
        "background_jobs", old_metadata,
        Column("job_id", String(64), primary_key=True),
        Column("status", String(16), nullable=False),
        Column("review_id", String(64), nullable=True),
        Column("error", String(4000), nullable=True),
        Column("case_id", String(256), nullable=True),
        Column("created", Float, nullable=False),
        Column("updated", Float, nullable=False),
        # deliberately missing items_total/items_completed/current_item_label
    )
    old_metadata.create_all(engine)

    # Now construct JobStore against this pre-existing old-schema database.
    store = JobStore(engine)
    job_id = store.create(case_id="CASE-MIGRATION-TEST")
    store.update_progress(job_id, completed=2, total=5, current_item_label="Response to Item 3")
    job = store.get(job_id)

    assert job.case_id == "CASE-MIGRATION-TEST"
    assert job.items_completed == 2
    assert job.items_total == 5
    assert job.current_item_label == "Response to Item 3"


def test_jobstore_migration_is_idempotent_across_repeated_construction(tmp_path):
    """Constructing JobStore more than once against the same database
    (e.g. a second gunicorn worker starting up) must not fail trying to
    re-add columns that already exist."""
    db_path = tmp_path / "repeat.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    JobStore(engine)
    JobStore(engine)  # must not raise "duplicate column" or similar
    store = JobStore(engine)
    job_id = store.create()
    store.update_progress(job_id, completed=1, total=1, current_item_label="done")
    assert store.get(job_id).items_completed == 1
