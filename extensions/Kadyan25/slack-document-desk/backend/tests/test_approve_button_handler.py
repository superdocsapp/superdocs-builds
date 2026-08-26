"""Exercises the real approve_button handler end to end: DB -> claim -> fake SuperDocs
call -> job/export update -> re-published Home tab. Only the Slack transport and the
SuperDocs network calls are faked; everything in between is the real code path."""
import json

from app.db.models import DocumentLink, PendingJob, ProcessedChange, RecentOutput
from app.db.session import SessionLocal
from app.services import approvals as approvals_module
from app.services import exports as exports_module
from app.slack.handlers.approve_button import handle_approve_change
from tests.fakes import FakeSuperDocsClient

JOB_ID = "job_e2e_approve_test"
CHANGE_ID = "chg_e2e"
USER_ID = "U_E2E_APPROVE_TEST"


def _cleanup(db):
    db.query(ProcessedChange).filter_by(job_id=JOB_ID).delete()
    db.query(RecentOutput).filter_by(job_id=JOB_ID).delete()
    db.query(PendingJob).filter_by(job_id=JOB_ID).delete()
    db.query(DocumentLink).filter_by(slack_user_id=USER_ID).delete()
    db.commit()


class _FakeSlackClient:
    def __init__(self):
        self.published = None
        self.uploaded = []

    def views_publish(self, user_id, view):
        self.published = (user_id, view)

    def files_upload_v2(self, channel, content, filename, initial_comment=None):
        self.uploaded.append((channel, filename, content))
        return {"file": {"permalink": f"https://fake.slack.com/files/{filename}"}}

    def conversations_open(self, users):
        return {"channel": {"id": f"D_FAKE_{users[0]}"}}


class _FakeLogger:
    def error(self, *args, **kwargs):
        raise AssertionError(f"unexpected logger.error call: {args}")


def test_approve_click_claims_calls_superdocs_updates_job_and_republishes_home_tab(monkeypatch):
    fake = FakeSuperDocsClient()
    fake.get_job_status = "completed"
    monkeypatch.setattr(approvals_module, "SuperDocsClient", lambda *a, **kw: fake)
    monkeypatch.setattr(exports_module, "SuperDocsClient", lambda *a, **kw: fake)

    db = SessionLocal()
    try:
        _cleanup(db)

        db.add(
            DocumentLink(
                slack_user_id=USER_ID,
                superdocs_document_id="doc_1",
                title="Weekly Status",
                is_focused=True,
            )
        )
        db.add(
            PendingJob(
                job_id=JOB_ID,
                slack_user_id=USER_ID,
                superdocs_session_id=f"slack-user-{USER_ID}",
                superdocs_document_id="doc_1",
                status="awaiting_approval",
                pending_changes_json=json.dumps(
                    [{"change_id": CHANGE_ID, "ai_explanation": "Reformat the due-dates list"}]
                ),
            )
        )
        db.commit()

        client = _FakeSlackClient()
        body = {"actions": [{"value": f"{JOB_ID}:{CHANGE_ID}"}], "user": {"id": USER_ID}}
        handle_approve_change(ack=lambda: None, body=body, client=client, logger=_FakeLogger())

        assert fake.approve_calls == [(f"slack-user-{USER_ID}", JOB_ID, True, CHANGE_ID)]
        assert len(fake.export_calls) == 1

        claimed = db.query(ProcessedChange).filter_by(job_id=JOB_ID, change_id=CHANGE_ID).one()
        assert claimed.approved is True

        job = db.query(PendingJob).filter_by(job_id=JOB_ID).one()
        assert job.status == "completed"

        output = db.query(RecentOutput).filter_by(job_id=JOB_ID).one_or_none()
        assert output is not None

        assert len(client.uploaded) == 1
        channel, filename, content = client.uploaded[0]
        assert channel == f"D_FAKE_{USER_ID}"
        assert content == b"fake-file-bytes"

        assert client.published is not None
        user_id, view = client.published
        assert user_id == USER_ID
        text = " ".join(
            b["text"]["text"] for b in view["blocks"] if b["type"] == "section" and "text" in b
        )
        assert "Nothing pending" in text
        assert "DOCX export ready" in text
    finally:
        _cleanup(db)
        db.close()


def test_second_approve_click_on_same_change_does_not_call_superdocs_again(monkeypatch):
    fake = FakeSuperDocsClient()
    fake.get_job_status = "completed"
    monkeypatch.setattr(approvals_module, "SuperDocsClient", lambda *a, **kw: fake)
    monkeypatch.setattr(exports_module, "SuperDocsClient", lambda *a, **kw: fake)

    db = SessionLocal()
    try:
        _cleanup(db)
        db.add(
            PendingJob(
                job_id=JOB_ID,
                slack_user_id=USER_ID,
                superdocs_session_id=f"slack-user-{USER_ID}",
                superdocs_document_id="doc_1",
                status="awaiting_approval",
                pending_changes_json=json.dumps(
                    [{"change_id": CHANGE_ID, "ai_explanation": "Reformat the due-dates list"}]
                ),
            )
        )
        db.commit()

        client = _FakeSlackClient()
        body = {"actions": [{"value": f"{JOB_ID}:{CHANGE_ID}"}], "user": {"id": USER_ID}}

        handle_approve_change(ack=lambda: None, body=body, client=client, logger=_FakeLogger())
        handle_approve_change(ack=lambda: None, body=body, client=client, logger=_FakeLogger())

        # Slack's own retry-on-timeout firing the same click twice must not double-apply.
        assert len(fake.approve_calls) == 1
        assert len(fake.export_calls) == 1
    finally:
        _cleanup(db)
        db.close()
