"""Wires up the Home tab's "Open" button, which renders on every document but
had no handler until now (so clicking it did nothing). Clicking Open switches
which document is *focused* — and the focused document is the one @mention edits
(see app_mention.py). This is what lets a user with several open documents point
their next edit at an older one, e.g. editing the same document two days apart
after sharing other files in between."""
from app.db.models import DocumentLink
from app.db.session import SessionLocal
from app.services.desk_state import build_desk_state
from app.slack.app import bolt_app
from app.slack.home_tab import build_home_tab_view


@bolt_app.action("open_document")
def handle_open_document(ack, body, client, logger):
    ack()
    document_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]

    db = SessionLocal()
    try:
        # Exactly one document is focused per user — the same invariant
        # file_shared's upload path maintains. Clear focus, then set it on the
        # clicked document. (An id that isn't this user's simply updates nothing.)
        db.query(DocumentLink).filter_by(slack_user_id=user_id).update({"is_focused": False})
        db.query(DocumentLink).filter_by(
            slack_user_id=user_id, superdocs_document_id=document_id
        ).update({"is_focused": True})
        db.commit()
        state = build_desk_state(db, user_id)
    finally:
        db.close()

    try:
        client.views_publish(user_id=user_id, view=build_home_tab_view(**state))
    except Exception as e:
        logger.error(f"Failed to re-publish home tab after open_document for {user_id}: {e}")
