from app.db.session import SessionLocal
from app.services.exports import redeliver_export
from app.slack.app import bolt_app


@bolt_app.action("download_export")
def handle_download_export(ack, body, client, logger):
    ack()
    output_id = int(body["actions"][0]["value"])

    db = SessionLocal()
    try:
        delivered = redeliver_export(db, output_id, client)
    finally:
        db.close()

    if not delivered:
        logger.error(f"No RecentOutput row for output_id={output_id}")
