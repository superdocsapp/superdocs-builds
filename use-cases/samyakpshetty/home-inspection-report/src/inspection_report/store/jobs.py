"""The work queue, in Postgres.

There is no broker here on purpose. `SELECT ... FOR UPDATE SKIP LOCKED` is a correct,
well-understood queue for this shape of work — a handful of jobs a day, each taking minutes —
and it means the queue is backed up, restored and reasoned about with the database it already
has, rather than by a second piece of infrastructure with its own failure modes.

Four properties, and each exists because of something that goes wrong without it:

* **Two workers never take the same job.** `FOR UPDATE SKIP LOCKED` inside the claim, so a
  second worker steps over a locked row instead of blocking on it.
* **A dead worker's job is reclaimed.** The claim holds a lease it renews while working. When
  a worker dies the lease expires and the row becomes claimable again.
* **A reclaimed job fails; it is not re-run.** This is the part that is specific to paying for
  AI operations. A job that died mid-flight may already have spent the operation, and
  re-running it would spend another. Nothing was applied to the report, so the honest outcome
  is a failure that says to start again — not a silent second charge.
* **One live job per inspection.** Enforced by a partial unique index rather than a check in
  the handler, so two API processes cannot both accept a `prepare` for the same report.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

import psycopg

from inspection_report.logging import get_logger

_log = get_logger("inspection_report.store.jobs")

# How long a claim is good for before another worker may take the row. Long enough to cover
# a slow AI call, short enough that a crash is noticed in a useful time.
LEASE_SECONDS = 600


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobConflict(RuntimeError):
    """This inspection already has a job in flight."""


@dataclass(frozen=True)
class Job:
    id: UUID
    inspection_id: UUID
    kind: str
    state: JobState
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    attempts: int

    @property
    def finished(self) -> bool:
        return self.state in (JobState.DONE, JobState.FAILED)


def _row_to_job(row: dict[str, Any]) -> Job:
    return Job(
        id=row["id"],
        inspection_id=row["inspection_id"],
        kind=row["kind"],
        state=JobState(row["state"]),
        payload=row["payload"] or {},
        result=row["result"],
        error=row["error"],
        attempts=row["attempts"],
    )


def worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def enqueue(
    conn: psycopg.Connection[dict[str, Any]],
    *,
    inspection_id: UUID,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> Job:
    """Put work on the queue. Raises :class:`JobConflict` if one is already in flight."""
    job_id = uuid4()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (id, inspection_id, kind, state, payload)
                VALUES (%s, %s, %s, 'queued', %s)
                RETURNING *
                """,
                (job_id, inspection_id, kind, json.dumps(payload or {})),
            )
            row = cur.fetchone()
        conn.commit()
    except psycopg.errors.UniqueViolation as exc:
        conn.rollback()
        raise JobConflict(
            "this inspection already has a review in flight. Wait for it to finish, or "
            "reload to see where it got to."
        ) from exc
    assert row is not None
    _log.info("job_enqueued", extra={"job": str(job_id), "kind": kind})
    return _row_to_job(row)


def claim(
    conn: psycopg.Connection[dict[str, Any]], *, kinds: tuple[str, ...] = ("prepare",)
) -> Job | None:
    """Take the oldest claimable job, or return None.

    Claimable means queued. A `running` row whose lease has expired is **not** claimed for
    re-execution — :func:`reap` fails it instead, because re-running work that may already
    have spent an operation is worse than reporting that it stopped.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs SET
                state = 'running',
                attempts = attempts + 1,
                worker = %s,
                started_at = coalesce(started_at, now()),
                lease_until = now() + make_interval(secs => %s)
            WHERE id = (
                SELECT id FROM jobs
                WHERE state = 'queued' AND kind = ANY(%s)
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """,
            (worker_name(), LEASE_SECONDS, list(kinds)),
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return None
    _log.info("job_claimed", extra={"job": str(row["id"]), "kind": row["kind"]})
    return _row_to_job(row)


def heartbeat(conn: psycopg.Connection[dict[str, Any]], job_id: UUID) -> None:
    """Extend the lease. A worker that stops calling this loses the job to :func:`reap`."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET lease_until = now() + make_interval(secs => %s) "
            "WHERE id = %s AND state = 'running'",
            (LEASE_SECONDS, job_id),
        )
    conn.commit()


def finish(
    conn: psycopg.Connection[dict[str, Any]],
    job_id: UUID,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Mark a job done or failed. One call, so a job never sits half-finished."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs SET
                state = %s, result = %s, error = %s, finished_at = now(), lease_until = NULL
            WHERE id = %s
            """,
            (
                JobState.FAILED if error else JobState.DONE,
                json.dumps(result) if result is not None else None,
                error,
                job_id,
            ),
        )
    conn.commit()
    _log.info("job_finished", extra={"job": str(job_id), "state": "failed" if error else "done"})


def reap(conn: psycopg.Connection[dict[str, Any]]) -> int:
    """Fail jobs whose worker stopped. Returns how many.

    Deliberately a failure rather than a requeue. The work may have spent an operation
    already; nothing it would have written was applied, so the safe and honest outcome is to
    say it stopped and let a person start it again.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs SET
                state = 'failed',
                error = 'the worker running this stopped before it finished. Nothing was '
                        'applied to the report — start the review again.',
                finished_at = now(),
                lease_until = NULL
            WHERE state = 'running' AND lease_until IS NOT NULL AND lease_until < now()
            RETURNING id
            """
        )
        reaped = cur.fetchall()
    conn.commit()
    if reaped:
        _log.warning("jobs_reaped", extra={"count": len(reaped)})
    return len(reaped)


def get(conn: psycopg.Connection[dict[str, Any]], job_id: UUID) -> Job | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    return _row_to_job(row) if row else None


def latest_for(conn: psycopg.Connection[dict[str, Any]], inspection_id: UUID) -> Job | None:
    """The most recent job for an inspection, so a reload can find its way back to one."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM jobs WHERE inspection_id = %s ORDER BY created_at DESC LIMIT 1",
            (inspection_id,),
        )
        row = cur.fetchone()
    return _row_to_job(row) if row else None


def age_seconds(started: dt.datetime | None) -> float:
    if started is None:
        return 0.0
    return (dt.datetime.now(dt.UTC) - started).total_seconds()
