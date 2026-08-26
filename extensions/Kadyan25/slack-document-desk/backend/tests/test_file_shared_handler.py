"""Exercises the real file_shared handler end to end, including a genuine Slack-retry
simulation: the same event_id delivered twice, exactly as Slack does when our ack takes
longer than ~3s (a file download + a SuperDocs upload routinely does). Only the Slack
transport, the file download (httpx), and the SuperDocs network calls are faked.

Mirrors test_app_mention_handler.py — this closes the coverage gap noted in issues.md,
where file_shared's retry-dedup had only unit coverage of claim_event, not a full
handler-level test proving no duplicate upload/ack on a retried delivery.
"""
from app.db.models import DocumentLink, ProcessedSlackEvent
from app.db.session import SessionLocal
from app.slack.handlers import upload_shortcut as upload_shortcut_module
from app.slack.handlers.upload_shortcut import handle_file_shared
from tests.fakes import FakeSuperDocsClient

USER_ID = "U_FILESHARE_TEST"
FILE_ID = "F_FILESHARE_TEST"
EVENT_ID = "Ev_fileshare_retry_test"
CHANNEL_ID = "C_FILESHARE_TEST"


class _FakeResponse:
    content = b"fake docx bytes"

    def raise_for_status(self):
        return None


class _FakeSlackClient:
    def __init__(self):
        self.posted = []
        self.files_info_calls = 0

    def files_info(self, file):
        self.files_info_calls += 1
        return {
            "file": {
                "name": "quarterly.docx",
                "url_private_download": "https://files.slack.com/private/quarterly.docx",
                "channels": [CHANNEL_ID],
            }
        }

    def chat_postMessage(self, channel, text, thread_ts=None):
        self.posted.append((channel, text))


class _FakeLogger:
    def error(self, *args, **kwargs):
        raise AssertionError(f"unexpected logger.error call: {args}")


def _cleanup(db):
    db.query(ProcessedSlackEvent).filter_by(event_id=EVENT_ID).delete()
    db.query(DocumentLink).filter_by(slack_user_id=USER_ID).delete()
    db.commit()


def test_retried_file_share_delivery_does_not_upload_or_ack_twice(monkeypatch):
    fake_sd = FakeSuperDocsClient()
    monkeypatch.setattr(upload_shortcut_module, "SuperDocsClient", lambda *a, **kw: fake_sd)
    monkeypatch.setattr(
        upload_shortcut_module.httpx, "get", lambda *a, **kw: _FakeResponse()
    )

    db = SessionLocal()
    try:
        _cleanup(db)

        event = {"user_id": USER_ID, "file_id": FILE_ID}
        client = _FakeSlackClient()

        # First delivery: genuinely processes.
        handle_file_shared(event=event, body={"event_id": EVENT_ID}, client=client, logger=_FakeLogger())
        # Slack retry of the exact same delivery — same event_id, same everything.
        handle_file_shared(event=event, body={"event_id": EVENT_ID}, client=client, logger=_FakeLogger())

        assert len(fake_sd.upload_calls) == 1, "retried delivery must not upload to SuperDocs a second time"
        assert len(client.posted) == 1, "retried delivery must not post a second ack message"
        assert client.files_info_calls == 1, "retried delivery must not re-fetch the file at all"

        links = db.query(DocumentLink).filter_by(slack_user_id=USER_ID).all()
        assert len(links) == 1, "retried delivery must not create a second document link"
        assert links[0].is_focused is True
        # The ack posts to the file's channel, not the user's DM.
        assert client.posted[0][0] == CHANNEL_ID
    finally:
        _cleanup(db)
        db.close()


def test_two_distinct_file_shares_both_process(monkeypatch):
    fake_sd = FakeSuperDocsClient()
    monkeypatch.setattr(upload_shortcut_module, "SuperDocsClient", lambda *a, **kw: fake_sd)
    monkeypatch.setattr(
        upload_shortcut_module.httpx, "get", lambda *a, **kw: _FakeResponse()
    )

    db = SessionLocal()
    other_event = "Ev_fileshare_second"
    try:
        _cleanup(db)
        db.query(ProcessedSlackEvent).filter_by(event_id=other_event).delete()
        db.commit()

        event = {"user_id": USER_ID, "file_id": FILE_ID}
        client = _FakeSlackClient()

        handle_file_shared(event=event, body={"event_id": EVENT_ID}, client=client, logger=_FakeLogger())
        handle_file_shared(event=event, body={"event_id": other_event}, client=client, logger=_FakeLogger())

        assert len(fake_sd.upload_calls) == 2, "two genuinely distinct file shares must both upload"
        assert len(client.posted) == 2
    finally:
        _cleanup(db)
        db.query(ProcessedSlackEvent).filter_by(event_id=other_event).delete()
        db.commit()
        db.close()
