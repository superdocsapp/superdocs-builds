import json
import logging

from app.db.models import PendingJob
from app.services.exports import export_and_record
from app.services.superdocs_client import SuperDocsClient

logger = logging.getLogger(__name__)

_OPEN_STATUSES = ("pending", "in_progress", "awaiting_approval")


def refresh_pending_jobs(db, slack_user_id: str, client) -> None:
    """SuperDocs is the source of truth for job state; ours is a cache. Called whenever
    the Home tab opens so a job that finished (or reached awaiting_approval) between
    visits shows up immediately rather than staying stuck at its last-known status.

    Each job is refreshed and exported independently: one job erroring (a transient
    SuperDocs failure, a since-deleted job) must not stop the rest of the user's jobs
    from reconciling, and must not stop the Home tab from rendering at all — that
    failure would otherwise propagate uncaught all the way out to app_home_opened.
    """
    jobs = (
        db.query(PendingJob)
        .filter(PendingJob.slack_user_id == slack_user_id, PendingJob.status.in_(_OPEN_STATUSES))
        .all()
    )
    if not jobs:
        return

    sd = SuperDocsClient()
    try:
        for job in jobs:
            try:
                remote = sd.get_job(job.job_id)
            except Exception:
                logger.exception(f"Failed to refresh job {job.job_id} — leaving its last-known status")
                continue
            job.status = remote["status"]
            pending_changes = remote.get("metadata", {}).get("pending_changes")
            if pending_changes is not None:
                job.pending_changes_json = json.dumps(pending_changes)
            db.commit()
    finally:
        sd.close()

    for job in jobs:
        if job.status == "completed":
            try:
                export_and_record(db, job, client)
            except Exception:
                logger.exception(f"Failed to auto-export job {job.job_id} — will retry on next Home tab open")
