"""SuperDocs' export endpoint returns the finished file's raw bytes directly (confirmed
live against a real key — see issues.md), not a JSON download-URL as originally assumed
during Phase 0 exploration. So instead of caching a link with a TTL, every export
uploads the bytes straight into the user's Slack DM. RecentOutput now just records that
a job's output was delivered (the idempotency guard for auto-export), not a cached link.
"""
import datetime

from app.db.models import RecentOutput
from app.services.superdocs_client import SuperDocsClient


def _upload_and_dm(client, slack_user_id: str, export: dict) -> str | None:
    """files_upload_v2's channel_id must be an actual channel/DM id (starts with
    C/G/D), not a raw user id — unlike chat.postMessage, this newer external-upload
    API does not resolve a user id into a DM channel automatically. conversations.open
    is idempotent (a DM that already exists just gets reopened), so no separate
    cache/lookup is needed."""
    dm = client.conversations_open(users=[slack_user_id])
    channel_id = dm["channel"]["id"]

    result = client.files_upload_v2(
        channel=channel_id,
        content=export["content"],
        filename=export["filename"],
        initial_comment="Here's your finished document.",
    )
    return (result.get("file") or {}).get("permalink")


def export_and_record(db, job, client, format: str = "docx") -> None:
    """Auto-exports and DMs the file once a job reaches 'completed', so the user gets
    the finished document without a separate action. Idempotent per job: skips if this
    job's output was already delivered."""
    existing = db.query(RecentOutput).filter_by(job_id=job.job_id).one_or_none()
    if existing is not None:
        return

    sd = SuperDocsClient()
    try:
        export = sd.export_document(job.superdocs_session_id, format=format)
    finally:
        sd.close()

    permalink = _upload_and_dm(client, job.slack_user_id, export)

    db.add(
        RecentOutput(
            slack_user_id=job.slack_user_id,
            job_id=job.job_id,
            superdocs_session_id=job.superdocs_session_id,
            superdocs_document_id=job.superdocs_document_id,
            export_format=format,
            download_url=permalink or "",
            # expires_at is vestigial now that there's no signed link to expire — kept
            # populated only because the column is still NOT NULL.
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=168),
        )
    )
    db.commit()


def redeliver_export(db, output_id: int, client) -> bool:
    """Re-exports fresh and re-DMs the file — used by the Home tab's Download button.
    Always re-exports rather than reusing a cached link, since SuperDocs' export has no
    stable link to cache in the first place; returns False if the output row is gone."""
    output = db.query(RecentOutput).filter_by(id=output_id).one_or_none()
    if output is None:
        return False

    sd = SuperDocsClient()
    try:
        export = sd.export_document(output.superdocs_session_id, format=output.export_format)
    finally:
        sd.close()

    permalink = _upload_and_dm(client, output.slack_user_id, export)
    if permalink:
        output.download_url = permalink
        db.commit()
    return True
