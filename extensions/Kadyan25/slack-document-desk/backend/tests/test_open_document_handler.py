"""The Home tab's Open button switches which document is focused (and the focused
document is what @mention edits). Covers the focus flip, the harmless re-click of
an already-active doc, and the "active" marker the tab renders."""
from app.db.models import DocumentLink
from app.db.session import SessionLocal
from app.slack.handlers.open_document import handle_open_document
from app.slack.home_tab import build_home_tab_view

USER_ID = "U_OPEN_TEST"


class _FakeSlackClient:
    def __init__(self):
        self.published = []

    def views_publish(self, user_id, view):
        self.published.append((user_id, view))


class _FakeLogger:
    def error(self, *args, **kwargs):
        raise AssertionError(f"unexpected logger.error call: {args}")


def _cleanup(db):
    db.query(DocumentLink).filter_by(slack_user_id=USER_ID).delete()
    db.commit()


def _seed_two_docs(db, focused="doc_A"):
    _cleanup(db)
    db.add(DocumentLink(slack_user_id=USER_ID, superdocs_document_id="doc_A", title="Alpha", is_focused=(focused == "doc_A")))
    db.add(DocumentLink(slack_user_id=USER_ID, superdocs_document_id="doc_B", title="Beta", is_focused=(focused == "doc_B")))
    db.commit()


def test_open_switches_focus_to_the_clicked_doc():
    db = SessionLocal()
    try:
        _seed_two_docs(db, focused="doc_A")
        client = _FakeSlackClient()
        acked = []

        handle_open_document(
            ack=lambda: acked.append(True),
            body={"user": {"id": USER_ID}, "actions": [{"value": "doc_B"}]},
            client=client,
            logger=_FakeLogger(),
        )

        assert acked == [True], "the interaction must be acked"
        db.expire_all()
        focus = {l.superdocs_document_id: l.is_focused for l in db.query(DocumentLink).filter_by(slack_user_id=USER_ID).all()}
        assert focus["doc_B"] is True, "the clicked document becomes focused"
        assert focus["doc_A"] is False, "the previously focused document is cleared"
        assert len(client.published) == 1, "the home tab is re-published after the switch"
    finally:
        _cleanup(db)
        db.close()


def test_reclicking_the_active_doc_keeps_exactly_one_focused():
    db = SessionLocal()
    try:
        _seed_two_docs(db, focused="doc_A")
        client = _FakeSlackClient()

        handle_open_document(
            ack=lambda: None,
            body={"user": {"id": USER_ID}, "actions": [{"value": "doc_A"}]},
            client=client,
            logger=_FakeLogger(),
        )

        db.expire_all()
        focused = [l.superdocs_document_id for l in db.query(DocumentLink).filter_by(slack_user_id=USER_ID, is_focused=True).all()]
        assert focused == ["doc_A"], "re-clicking the active doc leaves exactly it focused"
    finally:
        _cleanup(db)
        db.close()


def test_home_tab_marks_the_focused_document_active():
    view = build_home_tab_view(
        open_documents=[
            {"title": "Alpha", "superdocs_document_id": "doc_A", "is_focused": False},
            {"title": "Beta", "superdocs_document_id": "doc_B", "is_focused": True},
        ]
    )
    # Find the two document section blocks by their button values.
    buttons = {
        b["accessory"]["value"]: b
        for b in view["blocks"]
        if b.get("accessory", {}).get("action_id") == "open_document"
    }
    assert buttons["doc_B"]["accessory"]["text"]["text"] == "Active"
    assert "_active_" in buttons["doc_B"]["text"]["text"]
    assert buttons["doc_A"]["accessory"]["text"]["text"] == "Open"
    assert "_active_" not in buttons["doc_A"]["text"]["text"]
