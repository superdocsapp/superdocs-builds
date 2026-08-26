import re

from app.db.models import DocumentLink, PendingJob
from app.db.session import SessionLocal
from app.services.event_dedup import claim_event
from app.services.superdocs_client import SessionBusyError, SuperDocsClient
from app.services.user_session import get_or_create_session_id
from app.slack.app import bolt_app

_MENTION_RE = re.compile(r"<@[^>]+>\s*")


@bolt_app.event("app_mention")
def handle_app_mention(event, body, client, logger):
    db = SessionLocal()
    try:
        if not claim_event(db, body["event_id"]):
            return  # Slack retry of a delivery we already processed
    finally:
        db.close()

    user_id = event["user"]
    channel = event["channel"]
    thread_ts = event["ts"]
    instruction = _MENTION_RE.sub("", event.get("text", "")).strip()

    if not instruction:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Tell me what to change — e.g. `@Document Desk add a paragraph about rollout risk`.",
        )
        return

    db = SessionLocal()
    try:
        session_id = get_or_create_session_id(db, user_id)
        focused = db.query(DocumentLink).filter_by(slack_user_id=user_id, is_focused=True).one_or_none()
        if focused is None:
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="You don't have a document open yet — share a file in a channel first.",
            )
            return

        sd = SuperDocsClient()
        try:
            job = sd.chat_async(session_id, instruction, document_id=focused.superdocs_document_id)
        except SessionBusyError:
            # A prior change is still in flight or awaiting approval on this
            # session — SuperDocs allows only one active job at a time. Tell the
            # user how to unblock instead of crashing (500) with no message.
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="You've got a change waiting for approval — approve or reject it in your "
                "Home tab first, then mention me again.",
            )
            return
        finally:
            sd.close()

        db.add(
            PendingJob(
                job_id=job["job_id"],
                slack_user_id=user_id,
                superdocs_session_id=session_id,
                superdocs_document_id=focused.superdocs_document_id,
                status=job["status"],
            )
        )
        db.commit()
        doc_title = focused.title
    finally:
        db.close()

    try:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"On it — working on *{doc_title}*. Check your Home tab once it's ready for approval.",
        )
    except Exception as e:
        logger.error(f"Failed to acknowledge app_mention for {user_id}: {e}")
