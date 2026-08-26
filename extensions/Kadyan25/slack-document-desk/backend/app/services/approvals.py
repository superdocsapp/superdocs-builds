import json
import logging

from sqlalchemy.exc import IntegrityError

from app.db.models import PendingJob, ProcessedChange
from app.services.exports import export_and_record
from app.services.superdocs_client import SuperDocsClient

logger = logging.getLogger(__name__)


def claim_change(db, job_id: str, change_id: str, approved: bool) -> bool:
    """Atomically claims (job_id, change_id) via the table's unique constraint — first
    writer wins. Returns False if already claimed (a Slack retry of the same click),
    so the caller knows to skip calling SuperDocs again."""
    try:
        db.add(ProcessedChange(job_id=job_id, change_id=change_id, approved=approved))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def unclaim_change(db, job_id: str, change_id: str) -> None:
    """Releases a claim so a genuinely failed attempt can be retried — used only when
    the SuperDocs call itself raised, never after it succeeded. Without this, a
    transient SuperDocs failure (network blip, 5xx, timeout) would permanently lock
    the change as "processed" with nothing actually applied: claim_change is
    deliberately committed before the SuperDocs call (so a Slack retry of the same
    click can't double-apply), which means a mid-call failure has to be unwound
    explicitly rather than just left to roll back on its own."""
    db.query(ProcessedChange).filter_by(job_id=job_id, change_id=change_id).delete()
    db.commit()


def apply_decision(db, job_id: str, change_id: str, approved: bool, client) -> None:
    """Only ever called after claim_change() succeeds for this (job_id, change_id).
    Raises ApprovalFailed if the SuperDocs call itself fails, after releasing the
    claim — the caller is expected to catch it, tell the user, and let them retry."""
    job = db.query(PendingJob).filter_by(job_id=job_id).one_or_none()
    if job is None:
        return

    sd = SuperDocsClient()
    try:
        try:
            sd.approve_change(job.superdocs_session_id, job_id, approved, change_id)
            remote = sd.get_job(job_id)
        except Exception as exc:
            unclaim_change(db, job_id, change_id)
            raise ApprovalFailed(f"SuperDocs call failed for {job_id}/{change_id}: {exc}") from exc
    finally:
        sd.close()

    job.status = remote["status"]
    pending_changes = remote.get("metadata", {}).get("pending_changes")
    if pending_changes is not None:
        job.pending_changes_json = json.dumps(pending_changes)
    db.commit()

    if job.status == "completed":
        # The decision itself already succeeded and committed above — a failure here
        # is only the auto-export/DM step, not the approval, so it must not unclaim
        # or be reported as the approval having failed. Known gap, not fixed here (see
        # issues.md): once job.status is "completed" it's outside refresh_pending_jobs'
        # reconciliation filter, and no RecentOutput row exists for the Download button
        # to appear at all — a failed auto-export currently has no retry path in the UI.
        try:
            export_and_record(db, job, client)
        except Exception:
            logger.exception(f"Auto-export failed for completed job {job_id} — approval itself still succeeded")


class ApprovalFailed(Exception):
    pass
