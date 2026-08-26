from app.db.session import SessionLocal
from app.services.desk_state import build_desk_state
from app.services.sync import refresh_pending_jobs
from app.slack.app import bolt_app
from app.slack.home_tab import build_home_tab_view


@bolt_app.event("app_home_opened")
def handle_app_home_opened(client, event, logger):
    user_id = event["user"]

    db = SessionLocal()
    try:
        refresh_pending_jobs(db, user_id, client)
        state = build_desk_state(db, user_id)
    finally:
        db.close()

    try:
        client.views_publish(user_id=user_id, view=build_home_tab_view(**state))
    except Exception as e:
        logger.error(f"Failed to publish home tab for {user_id}: {e}")
