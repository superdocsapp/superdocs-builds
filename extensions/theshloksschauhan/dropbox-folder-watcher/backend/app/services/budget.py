"""Operation budget enforcement for folder configs."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.folder_config import FolderConfig
from app.models.job import Job, JobStatus


def billable_jobs_in_last_hour(db: Session, folder_config_id) -> int:
    """Count jobs that consumed billable SuperDocs ops in the rolling hour."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    return (
        db.query(Job)
        .filter(
            Job.folder_config_id == folder_config_id,
            Job.preview.is_(False),
            Job.status.in_([
                JobStatus.REVIEW_PENDING,
                JobStatus.APPROVED,
                JobStatus.EXPORTING,
                JobStatus.WRITING_BACK,
                JobStatus.COMPLETED,
            ]),
            Job.updated_at >= cutoff,
        )
        .count()
    )


def budget_allows_processing(db: Session, folder_config: FolderConfig) -> bool:
    """Return False when the folder's hourly operation budget is exhausted."""
    if folder_config.preview_mode:
        return True
    used = billable_jobs_in_last_hour(db, folder_config.id)
    return used < folder_config.operation_budget_per_hour
