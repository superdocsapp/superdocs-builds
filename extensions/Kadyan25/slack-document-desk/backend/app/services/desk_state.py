import json

from app.db.models import DocumentLink, PendingJob, RecentOutput


def build_desk_state(db, slack_user_id: str) -> dict:
    """DB rows -> the plain dicts build_home_tab_view expects. Assumes refresh_pending_jobs
    has already synced job status for this user (app_home_opened does this first)."""
    documents = db.query(DocumentLink).filter_by(slack_user_id=slack_user_id).all()
    jobs = db.query(PendingJob).filter_by(slack_user_id=slack_user_id).all()
    outputs = (
        db.query(RecentOutput)
        .filter_by(slack_user_id=slack_user_id)
        .order_by(RecentOutput.created_at.desc())
        .limit(5)
        .all()
    )

    open_documents = [
        {"title": d.title, "superdocs_document_id": d.superdocs_document_id, "is_focused": d.is_focused}
        for d in documents
    ]

    pending_approvals = []
    running_jobs = []
    for job in jobs:
        if job.status == "awaiting_approval" and job.pending_changes_json:
            for change in json.loads(job.pending_changes_json):
                pending_approvals.append({**change, "job_id": job.job_id})
        elif job.status in ("pending", "in_progress"):
            running_jobs.append({"job_id": job.job_id, "status": job.status})

    recent_output = [{"id": o.id, "export_format": o.export_format} for o in outputs]

    return {
        "open_documents": open_documents,
        "pending_approvals": pending_approvals,
        "running_jobs": running_jobs,
        "recent_output": recent_output,
    }
