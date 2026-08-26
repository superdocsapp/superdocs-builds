"""A failed SuperDocs call during approve/reject must not permanently lock the change
as 'processed' with nothing actually applied — found live as a real gap (see issues.md):
claim_change() commits before the SuperDocs call (deliberately, so a Slack retry of the
same click can't double-apply), so a mid-call failure has to release that claim
explicitly or the change can never be retried again."""
from app.db.models import PendingJob, ProcessedChange
from app.db.session import SessionLocal
from app.services import approvals as approvals_module
from app.services.approvals import ApprovalFailed, apply_decision, claim_change
from tests.fakes import FakeSuperDocsClient

JOB_ID = "job_retry_test"
CHANGE_ID = "chg_retry_test"


class _FakeSlackClient:
    def views_publish(self, user_id, view):
        pass

    def files_upload_v2(self, channel, content, filename, initial_comment=None):
        return {"file": {"permalink": "https://fake.slack.com/files/x"}}

    def conversations_open(self, users):
        return {"channel": {"id": f"D_FAKE_{users[0]}"}}


def test_failed_approve_call_releases_the_claim_so_a_retry_can_succeed(monkeypatch):
    fake = FakeSuperDocsClient()
    fake.fail_approve = True
    monkeypatch.setattr(approvals_module, "SuperDocsClient", lambda *a, **kw: fake)

    db = SessionLocal()
    try:
        db.query(ProcessedChange).filter_by(job_id=JOB_ID, change_id=CHANGE_ID).delete()
        db.query(PendingJob).filter_by(job_id=JOB_ID).delete()
        db.commit()

        db.add(
            PendingJob(
                job_id=JOB_ID,
                slack_user_id="U_RETRY_TEST",
                superdocs_session_id="slack-user-U_RETRY_TEST",
                superdocs_document_id="doc_1",
                status="awaiting_approval",
            )
        )
        db.commit()

        # First attempt: claim succeeds, SuperDocs call fails, claim must be released.
        assert claim_change(db, JOB_ID, CHANGE_ID, approved=True) is True
        try:
            apply_decision(db, JOB_ID, CHANGE_ID, approved=True, client=_FakeSlackClient())
            assert False, "expected ApprovalFailed"
        except ApprovalFailed:
            pass

        assert db.query(ProcessedChange).filter_by(job_id=JOB_ID, change_id=CHANGE_ID).count() == 0

        # Second attempt (the user clicking Approve again): must be allowed to retry,
        # and this time it succeeds.
        fake.fail_approve = False
        assert claim_change(db, JOB_ID, CHANGE_ID, approved=True) is True
        apply_decision(db, JOB_ID, CHANGE_ID, approved=True, client=_FakeSlackClient())

        assert len(fake.approve_calls) == 1
        assert db.query(ProcessedChange).filter_by(job_id=JOB_ID, change_id=CHANGE_ID).count() == 1
    finally:
        db.query(ProcessedChange).filter_by(job_id=JOB_ID, change_id=CHANGE_ID).delete()
        db.query(PendingJob).filter_by(job_id=JOB_ID).delete()
        db.commit()
        db.close()
