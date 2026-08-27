"""The worker: claims a job, does the slow part, records what happened.

Separate from the API on purpose. The alternative — a background task inside the web process
— dies with that process, and this work costs money: a run that vanishes on a deploy has
already been charged for. A worker that holds a lease means a death is *noticed*, and the
inspector is told to start again rather than left watching a spinner that will never resolve.

The loop is deliberately dull. Claim one job, renew the lease while working, record the
outcome, sleep if there was nothing to do. Scaling is another container; correctness under
two of them is `FOR UPDATE SKIP LOCKED` in the claim, not anything here.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from typing import Any
from uuid import UUID

from inspection_report.logging import get_logger, setup_logging
from inspection_report.store import db, jobs

_log = get_logger("inspection_report.worker")

IDLE_SLEEP_S = 2.0
HEARTBEAT_S = 30.0


class _Stopping:
    """Set by SIGTERM so a deploy finishes the job in hand instead of abandoning it."""

    def __init__(self) -> None:
        self.flag = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle)

    def _handle(self, *_: Any) -> None:
        _log.info("worker_stopping")
        self.flag.set()

    @property
    def stopping(self) -> bool:
        return self.flag.is_set()


def _heartbeat_until(job_id: UUID, done: threading.Event) -> None:
    """Renew the lease while the job runs, in its own connection.

    Its own connection because the job's connection is busy inside the work; sharing one
    would mean the heartbeat waits for exactly the thing it is meant to be reporting on.
    """
    while not done.wait(HEARTBEAT_S):
        try:
            with db.connect() as conn:
                jobs.heartbeat(conn, job_id)
        except Exception as exc:  # pragma: no cover - depends on a live database
            _log.warning("heartbeat_failed", extra={"error": type(exc).__name__})


def run_prepare(conn: Any, job: jobs.Job) -> dict[str, Any]:
    """The slow path that used to sit inside an HTTP request."""
    from inspection_report.api import app as api

    inspection = db.load_inspection(conn, job.inspection_id)
    if inspection is None:
        raise RuntimeError("the inspection was deleted while this was queued")

    # From SuperDocs, not from the local file: the report is built on the skeleton the
    # service returns for the registered format. `source` says which path produced it, and
    # travels back to the interface rather than being assumed.
    template, source = api._materialised_template(conn, inspection.template_key)
    result = api._run_prepare(
        conn,
        inspection=inspection,
        template=template,
        model_tier=str(job.payload.get("model_tier") or "core"),
    )
    return {
        "proposals": len(result.proposals),
        "template_source": source,
        # Which SuperDocs answered. The fake counts its own operations down from an invented
        # budget, and without this the interface showed that countdown as the real balance.
        "provider": api._provider(),
        "ops_charged": result.ops_charged,
        "ops_remaining": result.ops_remaining,
    }


HANDLERS = {"prepare": run_prepare}


def work_once(stopping: _Stopping | None = None) -> bool:
    """Claim and run one job. Returns whether there was anything to do."""
    with db.connect() as conn:
        jobs.reap(conn)
        job = jobs.claim(conn, kinds=tuple(HANDLERS))
        if job is None:
            return False

    done = threading.Event()
    beat = threading.Thread(target=_heartbeat_until, args=(job.id, done), daemon=True)
    beat.start()
    started = time.monotonic()
    try:
        with db.connect() as conn:
            result = HANDLERS[job.kind](conn, job)
        with db.connect() as conn:
            jobs.finish(conn, job.id, result=result)
        _log.info(
            "job_done", extra={"job": str(job.id), "seconds": round(time.monotonic() - started, 1)}
        )
    except Exception as exc:
        # The message reaches an inspector, so it names what happened rather than the type.
        with db.connect() as conn:
            jobs.finish(conn, job.id, error=f"{type(exc).__name__}: {exc}"[:800])
        _log.error("job_failed", extra={"job": str(job.id), "error": type(exc).__name__})
    finally:
        done.set()
    return True


def main() -> None:
    setup_logging(os.environ.get("LOG_FORMAT", "json"))
    stopping = _Stopping()
    _log.info("worker_started", extra={"worker": jobs.worker_name()})

    # The schema is the API's job to apply; the worker waits for it rather than racing.
    for _ in range(60):
        try:
            with db.connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 FROM jobs LIMIT 1")
            break
        except Exception:
            if stopping.stopping:
                return
            time.sleep(2.0)

    while not stopping.stopping:
        try:
            if not work_once(stopping):
                time.sleep(IDLE_SLEEP_S)
        except Exception as exc:  # pragma: no cover - the loop must not die
            _log.error("worker_loop_error", extra={"error": type(exc).__name__})
            time.sleep(IDLE_SLEEP_S)
    _log.info("worker_stopped")


if __name__ == "__main__":
    main()
