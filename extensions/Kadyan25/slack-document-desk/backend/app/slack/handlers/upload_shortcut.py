"""Named upload_shortcut.py per architecture.md's repo layout, but implemented as a
`file_shared` event listener rather than a custom Slack message shortcut — it fires for
any file shared in a channel the bot is in, which is a plainer match for the card's
"a file shared in a channel" than requiring the user to invoke a shortcut manually."""
import httpx

from app.config import settings
from app.db.models import DocumentLink
from app.db.session import SessionLocal
from app.services.event_dedup import claim_event
from app.services.superdocs_client import SuperDocsClient
from app.services.user_session import get_or_create_session_id
from app.slack.app import bolt_app


@bolt_app.event("file_shared")
def handle_file_shared(event, body, client, logger):
    db = SessionLocal()
    try:
        if not claim_event(db, body["event_id"]):
            return  # Slack retry of a delivery we already processed
    finally:
        db.close()

    user_id = event["user_id"]
    file_id = event["file_id"]

    file_info = client.files_info(file=file_id)["file"]
    filename = file_info["name"]

    resp = httpx.get(
        file_info["url_private_download"],
        headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
        follow_redirects=True,
    )
    resp.raise_for_status()
    content = resp.content

    db = SessionLocal()
    try:
        session_id = get_or_create_session_id(db, user_id)

        sd = SuperDocsClient()
        try:
            doc = sd.upload_document(session_id, filename, content)
        finally:
            sd.close()

        document_id = doc["durable_document_id"] or doc["document_id"]

        db.query(DocumentLink).filter_by(slack_user_id=user_id).update({"is_focused": False})
        link = db.query(DocumentLink).filter_by(
            slack_user_id=user_id, superdocs_document_id=document_id
        ).one_or_none()
        if link is None:
            db.add(
                DocumentLink(
                    slack_user_id=user_id,
                    superdocs_document_id=document_id,
                    title=doc["title"],
                    is_focused=True,
                )
            )
        else:
            link.title = doc["title"]
            link.is_focused = True
        db.commit()
    finally:
        db.close()

    # Slack stopped including channel_id on file_shared payloads; files.info's
    # `channels` list is what tells us where to post the acknowledgment.
    channels = file_info.get("channels") or []
    target_channel = channels[0] if channels else user_id
    try:
        client.chat_postMessage(
            channel=target_channel,
            text=f"Got it — *{filename}* is open in your Document Desk. "
            f"Mention me with an edit instruction, or check your Home tab.",
        )
    except Exception as e:
        logger.error(f"Failed to acknowledge file_shared for {user_id}: {e}")
