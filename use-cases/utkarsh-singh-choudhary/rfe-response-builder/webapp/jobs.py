"""
Background job queue for the webapp's real-run (`start_review`) path.

Before this module, `POST /generate` for a non-dry-run request called
`start_review()` synchronously inside the request -- which makes one
`chat_async` + `wait_for_job` round trip per RFE item plus a header turn,
easily 10-60+ seconds for a real filing. That ties up a gunicorn worker
(thread) for the whole duration, so a handful of concurrent real runs can
exhaust `--workers * --threads` and start queuing or timing out unrelated
requests, including dry runs and health checks on the same instance.

This module makes that path asynchronous: `POST /generate` enqueues a
`Job`, returns immediately with a redirect to a status page, and a small
`ThreadPoolExecutor` runs `start_review` in the background. The status
page polls `GET /jobs/<job_id>/status` (JSON) and redirects to the
review page once the job completes.

This is a pragmatic, dependency-light background queue -- NOT Celery/RQ.
It's in-process (`ThreadPoolExecutor`), so queued/running jobs are lost
if the process restarts (same durability ceiling the old synchronous
version had -- a killed request also lost its in-flight work). The
`JobStore` table is intentionally the same shape a Celery result backend
would need, so swapping in a real broker+worker later is a matter of
replacing the executor, not the data model or the routes.
"""
from __future__ import annotations

import logging
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import Column, Float, MetaData, String, Table, delete, insert, select, update
from sqlalchemy.engine import Engine

logger = logging.getLogger("rfe_response_builder.webapp.jobs")

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_metadata = MetaData()

jobs_table = Table(
    "background_jobs",
    _metadata,
    Column("job_id", String(64), primary_key=True),
    Column("status", String(16), nullable=False),
    Column("review_id", String(64), nullable=True),
    Column("error", String(4000), nullable=True),
    Column("case_id", String(256), nullable=True),
    Column("created", Float, nullable=False),
    Column("updated", Float, nullable=False),
)


@dataclass
class JobRecord:
    job_id: str
    status: str
    review_id: str | None
    error: str | None
    case_id: str | None
    created: float
    updated: float


class JobStore:
    """Same SQLAlchemy-engine pattern as `review_store.ReviewSessionStore`
    -- pass the same engine so job records live in the same database as
    review sessions (one less moving part to provision/monitor), while
    keeping the table itself separate and swappable."""

    def __init__(self, engine: Engine, ttl_s: int = 3600):
        self.engine = engine
        self.ttl_s = ttl_s
        _metadata.create_all(self.engine, tables=[jobs_table])

    def create(self, case_id: str | None = None) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        with self.engine.begin() as conn:
            conn.execute(insert(jobs_table).values(
                job_id=job_id, status=STATUS_PENDING, review_id=None, error=None,
                case_id=case_id, created=now, updated=now,
            ))
        return job_id

    def mark_running(self, job_id: str) -> None:
        self._update(job_id, status=STATUS_RUNNING)

    def mark_completed(self, job_id: str, review_id: str) -> None:
        self._update(job_id, status=STATUS_COMPLETED, review_id=review_id)

    def mark_failed(self, job_id: str, error: str) -> None:
        self._update(job_id, status=STATUS_FAILED, error=error[:4000])

    def _update(self, job_id: str, **fields) -> None:
        fields["updated"] = time.time()
        with self.engine.begin() as conn:
            conn.execute(update(jobs_table).where(jobs_table.c.job_id == job_id).values(**fields))

    def get(self, job_id: str) -> JobRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(jobs_table).where(jobs_table.c.job_id == job_id)).fetchone()
        return JobRecord(*row) if row else None

    def prune_stale(self) -> None:
        cutoff = time.time() - self.ttl_s
        with self.engine.begin() as conn:
            conn.execute(delete(jobs_table).where(jobs_table.c.created < cutoff))


class JobRunner:
    """Thin wrapper around a ThreadPoolExecutor that updates `JobStore`
    status transitions around a submitted callable. `max_workers` bounds
    how many real drafting runs can be in flight at once on this
    instance -- deliberately small (default 2) since each one holds a
    long-lived SuperDocs conversation, not because the thread itself is
    expensive."""

    def __init__(self, store: JobStore, max_workers: int = 2):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rfe-job")

    def submit(self, job_id: str, fn: Callable[[], str]) -> None:
        """`fn` must return the review_id on success, or raise."""

        def _run():
            self.store.mark_running(job_id)
            try:
                review_id = fn()
                self.store.mark_completed(job_id, review_id)
            except Exception as e:  # noqa: BLE001 - deliberately broad: any failure must
                # still mark the job failed and be visible to the person
                # waiting on the status page, not vanish into a thread's
                # unhandled-exception log line.
                logger.error("background job %s failed: %s\n%s", job_id, e, traceback.format_exc())
                self.store.mark_failed(job_id, str(e))

        self.executor.submit(_run)
