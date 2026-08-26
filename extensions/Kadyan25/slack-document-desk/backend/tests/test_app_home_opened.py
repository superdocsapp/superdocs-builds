"""Exercises the real handler against the real (containerized) Postgres — the only thing
faked is the Slack client, since there's no live bot token in this environment yet."""
from app.db.models import DocumentLink
from app.db.session import SessionLocal
from app.slack.handlers.app_home_opened import handle_app_home_opened


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


def test_publishes_empty_home_tab_for_a_new_user():
    client = _FakeSlackClient()
    handle_app_home_opened(client=client, event={"user": "U_TEST_EMPTY"}, logger=_FakeLogger())

    assert client.published is not None
    user_id, view = client.published
    assert user_id == "U_TEST_EMPTY"
    assert view["type"] == "home"


def test_publishes_open_document_from_db():
    db = SessionLocal()
    try:
        db.query(DocumentLink).filter_by(slack_user_id="U_TEST_WITH_DOC").delete()
        db.commit()

        db.add(
            DocumentLink(
                slack_user_id="U_TEST_WITH_DOC",
                superdocs_document_id="dc-test-1",
                title="Weekly Status",
                is_focused=True,
            )
        )
        db.commit()

        client = _FakeSlackClient()
        handle_app_home_opened(client=client, event={"user": "U_TEST_WITH_DOC"}, logger=_FakeLogger())

        _, view = client.published
        text = " ".join(
            b["text"]["text"] for b in view["blocks"] if b["type"] == "section" and "text" in b
        )
        assert "Weekly Status" in text
    finally:
        db.query(DocumentLink).filter_by(slack_user_id="U_TEST_WITH_DOC").delete()
        db.commit()
        db.close()
