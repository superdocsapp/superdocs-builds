"""The work queue, against a real Postgres.

The queue is `FOR UPDATE SKIP LOCKED` in a table rather than a broker, so the properties that
matter are database properties and there is no honest way to test them against a fake.
"""

from __future__ import annotations

import datetime as dt
import threading

import pytest

from inspection_report import sample
from inspection_report.store import db, jobs

pytestmark = pytest.mark.postgres


@pytest.fixture
def conn():  # type: ignore[no-untyped-def]
    try:
        with db.connect():
            pass
    except Exception as exc:
        # Any connection failure means "no database here", so the kind does not matter.
        pytest.skip(f"needs a Postgres ({type(exc).__name__}); try `make test-db`")
    with db.connect() as connection:
        db.apply_schema(connection)
        before = _inspection_ids(connection)
        yield connection
        # Through the application's own delete, not raw SQL: that is what reclaims the
        # blobs. Deleting the rows directly left the photographs on the volume — a tidy
        # database and a growing disk.
        for made_id in _inspection_ids(connection) - before:
            db.delete_inspection(connection, made_id)


def _inspection_ids(connection) -> set:  # type: ignore[no-untyped-def]
    """These tests share the application's database; they must not litter it."""
    with connection.cursor() as cur:
        cur.execute("SELECT id FROM inspections")
        return {row["id"] for row in cur.fetchall()}


@pytest.fixture
def inspection(conn):  # type: ignore[no-untyped-def]
    made = sample.sample_inspection()
    made.findings = made.findings[:1]
    db.save_inspection(conn, made)
    # The queue is FIFO across the whole table, so a leftover row from another test decides
    # which job a claim returns. These tests own the queue.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM jobs")
    conn.commit()
    return made


class TestTheHappyPath:
    def test_enqueue_claim_finish(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        queued = jobs.enqueue(
            conn, inspection_id=inspection.id, kind="prepare", payload={"model_tier": "core"}
        )
        assert queued.state is jobs.JobState.QUEUED

        claimed = jobs.claim(conn)
        assert claimed is not None and claimed.id == queued.id
        assert claimed.state is jobs.JobState.RUNNING
        assert claimed.attempts == 1
        assert claimed.payload["model_tier"] == "core"

        jobs.finish(conn, claimed.id, result={"proposals": 8})
        done = jobs.get(conn, claimed.id)
        assert done is not None and done.state is jobs.JobState.DONE
        assert done.result == {"proposals": 8}
        assert done.finished

    def test_an_empty_queue_claims_nothing(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        assert jobs.claim(conn) is None


class TestTwoWorkers:
    def test_the_same_job_is_never_claimed_twice(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        """SKIP LOCKED is the whole reason this needs no broker."""
        jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")

        claimed: list[jobs.Job | None] = []
        errors: list[BaseException] = []

        def take() -> None:
            try:
                with db.connect() as own:  # a connection each, as two workers would have
                    claimed.append(jobs.claim(own))
            except BaseException as exc:  # pragma: no cover - reported, not swallowed
                errors.append(exc)

        threads = [threading.Thread(target=take) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        got = [c for c in claimed if c is not None]
        assert len(got) == 1, f"{len(got)} workers claimed the same job"

    def test_one_live_job_per_inspection(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        """A second review of one report is a mistake, and the database refuses it."""
        jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")
        with pytest.raises(jobs.JobConflict):
            jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")

    def test_a_finished_job_frees_the_inspection(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        first = jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")
        jobs.finish(conn, first.id, result={})
        second = jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")
        assert second.id != first.id


class TestAWorkerThatDies:
    """The reason the worker is a separate process at all."""

    def _expire(self, conn, job_id) -> None:  # type: ignore[no-untyped-def]
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET lease_until = %s WHERE id = %s",
                (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5), job_id),
            )
        conn.commit()

    def test_an_expired_lease_is_failed_not_rerun(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        """Re-running work that may already have spent an operation would spend another."""
        queued = jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")
        claimed = jobs.claim(conn)
        assert claimed is not None
        self._expire(conn, claimed.id)

        assert jobs.reap(conn) == 1
        after = jobs.get(conn, queued.id)
        assert after is not None
        assert after.state is jobs.JobState.FAILED
        assert "start the review again" in (after.error or "")

        assert jobs.claim(conn) is None, "a dead job must not be picked up and re-run"

    def test_after_reaping_a_new_review_can_be_started(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        queued = jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")
        claimed = jobs.claim(conn)
        assert claimed is not None
        self._expire(conn, claimed.id)
        jobs.reap(conn)

        fresh = jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")
        assert fresh.id != queued.id

    def test_a_heartbeat_keeps_the_job(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")
        claimed = jobs.claim(conn)
        assert claimed is not None
        self._expire(conn, claimed.id)
        jobs.heartbeat(conn, claimed.id)  # a live worker renews before the reaper runs

        assert jobs.reap(conn) == 0
        still = jobs.get(conn, claimed.id)
        assert still is not None and still.state is jobs.JobState.RUNNING


class TestFindingTheWayBack:
    def test_the_latest_job_is_reported(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        """A reload has to be able to rejoin a review that is already running."""
        first = jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")
        jobs.finish(conn, first.id, result={})
        second = jobs.enqueue(conn, inspection_id=inspection.id, kind="prepare")

        latest = jobs.latest_for(conn, inspection.id)
        assert latest is not None and latest.id == second.id

    def test_no_job_is_not_an_error(self, conn, inspection) -> None:  # type: ignore[no-untyped-def]
        assert jobs.latest_for(conn, inspection.id) is None
