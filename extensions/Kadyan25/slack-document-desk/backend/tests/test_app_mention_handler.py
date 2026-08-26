"""Exercises the real app_mention handler end to end, including a genuine Slack-retry
simulation: the same event_id delivered twice, exactly as Slack does when our ack takes
longer than ~3s (see issues.md — this is the exact live bug the fix here guards against).
Only the Slack transport and the SuperDocs network calls are faked."""
from app.db.models import DocumentLink, PendingJob, ProcessedSlackEvent
from app.db.session import SessionLocal
from app.services import event_dedup as event_dedup_module
from app.slack.handlers import app_mention as app_mention_module
from app.slack.handlers.app_mention import handle_app_mention
from tests.fakes import FakeSuperDocsClient

USER_ID = "U_MENTION_TEST"
EVENT_ID = "Ev_mention_retry_test"


class _FakeSlackClient:
    def __init__(self):
        self.posted = []

    def chat_postMessage(self, channel, text, thread_ts=None):
        self.posted.append((channel, text))


class _FakeLogger:
    def error(self, *args, **kwargs):
        raise AssertionError(f"unexpected logger.error call: {args}")


def _cleanup(db):
    db.query(ProcessedSlackEvent).filter_by(event_id=EVENT_ID).delete()
    db.query(PendingJob).filter_by(slack_user_id=USER_ID).delete()
    db.query(DocumentLink).filter_by(slack_user_id=USER_ID).delete()
    db.commit()


def test_retried_mention_delivery_does_not_call_superdocs_twice(monkeypatch):
    fake = FakeSuperDocsClient()
    monkeypatch.setattr(app_mention_module, "SuperDocsClient", lambda *a, **kw: fake)

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
        db.commit()

        event = {"user": USER_ID, "channel": "C_TEST", "ts": "123.456", "text": "<@BOTID> add a risk note"}
        client = _FakeSlackClient()

        # First delivery: genuinely processes.
        handle_app_mention(event=event, body={"event_id": EVENT_ID}, client=client, logger=_FakeLogger())
        # Slack retry of the exact same delivery — same event_id, same everything.
        handle_app_mention(event=event, body={"event_id": EVENT_ID}, client=client, logger=_FakeLogger())

        assert len(fake.chat_calls) == 1, "retried delivery must not call chat_async a second time"
        assert len(client.posted) == 1, "retried delivery must not post a second ack message"

        jobs = db.query(PendingJob).filter_by(slack_user_id=USER_ID).all()
        assert len(jobs) == 1
    finally:
        _cleanup(db)
        db.close()


def test_mention_on_a_busy_session_replies_helpfully_and_does_not_crash(monkeypatch):
    """When SuperDocs rejects chat_async with a 409 (a prior change is still
    awaiting approval on the session), the handler must tell the user how to
    unblock and return cleanly — not crash with a 500 and no message (the exact
    silent dead-end found live; see issues.md)."""
    fake = FakeSuperDocsClient()
    fake.fail_chat_with_session_busy = True
    monkeypatch.setattr(app_mention_module, "SuperDocsClient", lambda *a, **kw: fake)

    busy_event = "Ev_mention_busy"
    db = SessionLocal()
    try:
        db.query(ProcessedSlackEvent).filter_by(event_id=busy_event).delete()
        _cleanup(db)
        db.add(
            DocumentLink(
                slack_user_id=USER_ID,
                superdocs_document_id="doc_1",
                title="Weekly Status",
                is_focused=True,
            )
        )
        db.commit()

        event = {"user": USER_ID, "channel": "C_TEST", "ts": "123.456", "text": "<@BOTID> add a risk note"}
        client = _FakeSlackClient()

        # Must not raise even though chat_async 409s.
        handle_app_mention(event=event, body={"event_id": busy_event}, client=client, logger=_FakeLogger())

        assert len(fake.chat_calls) == 0, "a busy session should not record a successful chat call"
        assert any("approve or reject" in text.lower() for _, text in client.posted), (
            "the user must be told to resolve the pending change first"
        )
        jobs = db.query(PendingJob).filter_by(slack_user_id=USER_ID).all()
        assert len(jobs) == 0, "no PendingJob should be created when the session was busy"
    finally:
        db.query(ProcessedSlackEvent).filter_by(event_id=busy_event).delete()
        _cleanup(db)
        db.close()


def test_different_mentions_both_process_independently(monkeypatch):
    fake = FakeSuperDocsClient()
    monkeypatch.setattr(app_mention_module, "SuperDocsClient", lambda *a, **kw: fake)

    db = SessionLocal()
    try:
        _cleanup(db)
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_mention_a").delete()
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_mention_b").delete()
        db.commit()

        db.add(
            DocumentLink(
                slack_user_id=USER_ID,
                superdocs_document_id="doc_1",
                title="Weekly Status",
                is_focused=True,
            )
        )
        db.commit()

        event = {"user": USER_ID, "channel": "C_TEST", "ts": "123.456", "text": "<@BOTID> add a note"}
        client = _FakeSlackClient()

        handle_app_mention(event=event, body={"event_id": "Ev_mention_a"}, client=client, logger=_FakeLogger())
        handle_app_mention(event=event, body={"event_id": "Ev_mention_b"}, client=client, logger=_FakeLogger())

        assert len(fake.chat_calls) == 2, "two genuinely distinct mentions must both process"
    finally:
        _cleanup(db)
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_mention_a").delete()
        db.query(ProcessedSlackEvent).filter_by(event_id="Ev_mention_b").delete()
        db.commit()
        db.close()
