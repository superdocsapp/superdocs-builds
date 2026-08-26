from app.db.session import SessionLocal
from app.services.approvals import ApprovalFailed, apply_decision, claim_change
from app.services.desk_state import build_desk_state
from app.slack.app import bolt_app
from app.slack.home_tab import build_home_tab_view


@bolt_app.action("approve_change")
def handle_approve_change(ack, body, client, logger):
    ack()
    job_id, change_id = body["actions"][0]["value"].split(":", 1)
    user_id = body["user"]["id"]

    failed = False
    db = SessionLocal()
    try:
        if claim_change(db, job_id, change_id, approved=True):
            try:
                apply_decision(db, job_id, change_id, approved=True, client=client)
            except ApprovalFailed:
                logger.exception(f"Approve failed for {job_id}/{change_id}")
                failed = True
        state = build_desk_state(db, user_id)
    finally:
        db.close()

    if failed:
        try:
            client.chat_postMessage(
                channel=user_id,
                text="Something went wrong applying that change in SuperDocs. "
                "Nothing was changed — click Approve again to retry.",
            )
        except Exception as e:
            logger.error(f"Failed to DM approve-failure notice to {user_id}: {e}")

    try:
        client.views_publish(user_id=user_id, view=build_home_tab_view(**state))
    except Exception as e:
        logger.error(f"Failed to re-publish home tab for {user_id}: {e}")
