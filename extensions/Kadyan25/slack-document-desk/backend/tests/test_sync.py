"""Simulates a kill-mid-flow-and-restart: a PendingJob left at a stale status (as if the
process died before ever seeing SuperDocs finish the job), then the next Home tab open
must reconcile it to the true remote state. No live SuperDocs key needed — the client is
faked, since what's under test is our own reconciliation logic, not SuperDocs itself.
"""
import datetime

from app.db.models import PendingJob, RecentOutput
from app.db.session import SessionLocal
from app.services import exports as exports_module
from app.services import sync as sync_module
from tests.fakes import FakeSuperDocsClient


class _FakeSlackClient:
    def __init__(self):
        self.uploaded = []

    def files_upload_v2(self, channel, content, filename, initial_comment=None):
        self.uploaded.append((channel, filename, content))
        return {"file": {"permalink": f"https://fake.slack.com/files/{filename}"}}

    def conversations_open(self, users):
        return {"channel": {"id": f"D_FAKE_{users[0]}"}}


def test_restart_reconciles_stale_job_to_completed_and_exports(monkeypatch):
    monkeypatch.setattr(sync_module, "SuperDocsClient", FakeSuperDocsClient)
    monkeypatch.setattr(exports_module, "SuperDocsClient", FakeSuperDocsClient)

    db = SessionLocal()
    try:
        db.query(RecentOutput).filter_by(job_id="job_restart_test").delete()
        db.query(PendingJob).filter_by(job_id="job_restart_test").delete()
        db.commit()

        # Left behind as "in_progress" — as if the process died right after chat_async
        # returned but before it ever learned the job had actually finished.
        db.add(
            PendingJob(
                job_id="job_restart_test",
                slack_user_id="U_RESTART_TEST",
                superdocs_session_id="slack-user-U_RESTART_TEST",
                superdocs_document_id="doc_1",
                status="in_progress",
            )
        )
        db.commit()

        client = _FakeSlackClient()
        sync_module.refresh_pending_jobs(db, "U_RESTART_TEST", client)

        job = db.query(PendingJob).filter_by(job_id="job_restart_test").one()
        assert job.status == "completed"

        output = db.query(RecentOutput).filter_by(job_id="job_restart_test").one_or_none()
        assert output is not None
        assert output.download_url == "https://fake.slack.com/files/export.docx"

        assert len(client.uploaded) == 1
        channel, filename, content = client.uploaded[0]
        assert channel == "D_FAKE_U_RESTART_TEST"
        assert content == b"fake-file-bytes"
    finally:
        db.query(RecentOutput).filter_by(job_id="job_restart_test").delete()
        db.query(PendingJob).filter_by(job_id="job_restart_test").delete()
        db.commit()
        db.close()


def test_redeliver_export_always_reexports_and_reuploads(monkeypatch):
    """SuperDocs' export has no stable link to cache (confirmed live — see issues.md),
    so the Download button always re-exports and re-DMs the file fresh, regardless of
    how recently it was last delivered."""
    fake_superdocs = FakeSuperDocsClient()
    monkeypatch.setattr(exports_module, "SuperDocsClient", lambda *a, **kw: fake_superdocs)

    db = SessionLocal()
    try:
        db.query(RecentOutput).filter_by(job_id="job_redeliver_test").delete()
        db.query(PendingJob).filter_by(job_id="job_redeliver_test").delete()
        db.commit()

        db.add(
            PendingJob(
                job_id="job_redeliver_test",
                slack_user_id="U_REDELIVER_TEST",
                superdocs_session_id="slack-user-U_REDELIVER_TEST",
                superdocs_document_id="doc_1",
                status="completed",
            )
        )
        db.commit()

        existing = RecentOutput(
            slack_user_id="U_REDELIVER_TEST",
            job_id="job_redeliver_test",
            superdocs_session_id="slack-user-U_REDELIVER_TEST",
            superdocs_document_id="doc_1",
            export_format="docx",
            download_url="https://fake.slack.com/files/stale.docx",
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=100),
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)

        client = _FakeSlackClient()
        delivered = exports_module.redeliver_export(db, existing.id, client)

        assert delivered is True
        assert len(fake_superdocs.export_calls) == 1
        assert len(client.uploaded) == 1

        db.refresh(existing)
        assert existing.download_url == "https://fake.slack.com/files/export.docx"
    finally:
        db.query(RecentOutput).filter_by(job_id="job_redeliver_test").delete()
        db.query(PendingJob).filter_by(job_id="job_redeliver_test").delete()
        db.commit()
        db.close()


def test_one_failing_job_does_not_block_the_rest_from_reconciling(monkeypatch):
    """Found live as a real gap (see issues.md): the old loop had one db.commit() after
    the whole for-loop and no per-job exception handling, so one job erroring (a
    transient SuperDocs failure) raised out of refresh_pending_jobs uncaught — which
    would have propagated all the way out to app_home_opened and stopped the Home tab
    from rendering at all, for every job, not just the failing one."""
    fake = FakeSuperDocsClient()
    fake.fail_get_job_for = {"job_isolation_bad"}
    monkeypatch.setattr(sync_module, "SuperDocsClient", lambda *a, **kw: fake)
    monkeypatch.setattr(exports_module, "SuperDocsClient", lambda *a, **kw: fake)

    db = SessionLocal()
    try:
        for job_id in ("job_isolation_bad", "job_isolation_good"):
            db.query(RecentOutput).filter_by(job_id=job_id).delete()
            db.query(PendingJob).filter_by(job_id=job_id).delete()
        db.commit()

        db.add(
            PendingJob(
                job_id="job_isolation_bad",
                slack_user_id="U_ISOLATION_TEST",
                superdocs_session_id="slack-user-U_ISOLATION_TEST",
                superdocs_document_id="doc_1",
                status="in_progress",
            )
        )
        db.add(
            PendingJob(
                job_id="job_isolation_good",
                slack_user_id="U_ISOLATION_TEST",
                superdocs_session_id="slack-user-U_ISOLATION_TEST",
                superdocs_document_id="doc_1",
                status="in_progress",
            )
        )
        db.commit()

        client = _FakeSlackClient()
        # Must not raise, despite job_isolation_bad's get_job failing every time.
        sync_module.refresh_pending_jobs(db, "U_ISOLATION_TEST", client)

        bad = db.query(PendingJob).filter_by(job_id="job_isolation_bad").one()
        good = db.query(PendingJob).filter_by(job_id="job_isolation_good").one()
        assert bad.status == "in_progress"  # untouched, left for the next attempt
        assert good.status == "completed"  # reconciled despite the sibling job's failure

        good_output = db.query(RecentOutput).filter_by(job_id="job_isolation_good").one_or_none()
        assert good_output is not None
        bad_output = db.query(RecentOutput).filter_by(job_id="job_isolation_bad").one_or_none()
        assert bad_output is None
    finally:
        for job_id in ("job_isolation_bad", "job_isolation_good"):
            db.query(RecentOutput).filter_by(job_id=job_id).delete()
            db.query(PendingJob).filter_by(job_id=job_id).delete()
        db.commit()
        db.close()


def test_redeliver_export_returns_false_for_missing_output():
    db = SessionLocal()
    try:
        client = _FakeSlackClient()
        delivered = exports_module.redeliver_export(db, 999999999, client)
        assert delivered is False
        assert client.uploaded == []
    finally:
        db.close()
