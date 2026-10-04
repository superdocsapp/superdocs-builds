"""State machine for job processing.

Defines valid transitions, enforces them, and logs every transition
as an append-only event for full auditability.

The system must survive being killed midway through a run and continue
from the correct point after restart — this is achieved by persisting
state in the database and validating transitions atomically.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.job import Job, JobStatus
from app.models.event import Event

logger = logging.getLogger(__name__)


# ---------- Valid transitions ----------

VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.DISCOVERED: {JobStatus.STABILIZING, JobStatus.FAILED},
    JobStatus.STABILIZING: {JobStatus.QUEUED, JobStatus.DISCOVERED, JobStatus.FAILED},
    JobStatus.QUEUED: {JobStatus.PROCESSING, JobStatus.FAILED},
    JobStatus.PROCESSING: {JobStatus.REVIEW_PENDING, JobStatus.FAILED},
    JobStatus.REVIEW_PENDING: {JobStatus.APPROVED, JobStatus.REJECTED, JobStatus.FAILED},
    JobStatus.APPROVED: {JobStatus.EXPORTING, JobStatus.FAILED},
    JobStatus.REJECTED: set(),  # Terminal
    JobStatus.EXPORTING: {JobStatus.WRITING_BACK, JobStatus.FAILED},
    JobStatus.WRITING_BACK: {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),  # Terminal
    JobStatus.FAILED: {JobStatus.QUEUED},  # Can retry from FAILED -> QUEUED
}


class InvalidTransition(Exception):
    """Raised when a state transition is not allowed."""
    def __init__(self, job_id: UUID, from_state: JobStatus, to_state: JobStatus):
        self.job_id = job_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid transition for job {job_id}: "
            f"{from_state.value} -> {to_state.value}"
        )


def transition(
    db: Session,
    job: Job,
    to_state: JobStatus,
    actor: str = "system",
    detail: Optional[str] = None,
) -> Job:
    """Transition a job to a new state.

    Validates the transition, updates the job, and logs an event.
    All within the caller's transaction — no implicit commit.

    Args:
        db: Database session (caller controls the transaction).
        job: The job to transition.
        to_state: Target state.
        actor: Who/what initiated this transition.
        detail: Optional context (error message, approval note, etc.).

    Returns:
        The updated job.

    Raises:
        InvalidTransition: If the transition is not allowed.
    """
    from_state = job.status

    # Validate
    allowed = VALID_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise InvalidTransition(job.id, from_state, to_state)

    # Update job state
    old_status_value = from_state.value
    job.status = to_state
    job.updated_at = datetime.now(timezone.utc)

    if to_state == JobStatus.FAILED and detail:
        job.error_message = detail

    # Log the event (append-only audit trail)
    event = Event(
        job_id=job.id,
        from_state=old_status_value,
        to_state=to_state.value,
        actor=actor,
        detail=detail,
    )
    db.add(event)
    db.flush()

    logger.info(
        "Job %s: %s -> %s (actor=%s, detail=%s)",
        job.id, old_status_value, to_state.value, actor,
        detail[:80] if detail else None,
    )

    return job


def can_transition(job: Job, to_state: JobStatus) -> bool:
    """Check if a transition is valid without performing it."""
    allowed = VALID_TRANSITIONS.get(job.status, set())
    return to_state in allowed


def get_allowed_transitions(job: Job) -> set[JobStatus]:
    """Get all valid next states for a job."""
    return VALID_TRANSITIONS.get(job.status, set())


def is_terminal(job: Job) -> bool:
    """Check if a job is in a terminal state (no further transitions possible)."""
    return len(VALID_TRANSITIONS.get(job.status, set())) == 0


def claim_job(
    db: Session,
    job_id: UUID,
    worker_id: str,
) -> Optional[Job]:
    """Atomically claim a QUEUED job for processing.

    Uses a conditional UPDATE to prevent two workers from grabbing
    the same job — only one succeeds, the other gets None.

    This is the core concurrency mechanism for the worker lease pattern.
    """
    from sqlalchemy import update

    result = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.QUEUED)
        .values(
            status=JobStatus.PROCESSING,
            locked_by=worker_id,
            locked_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        .returning(Job.id)
    )
    db.flush()

    row = result.first()
    if row is None:
        logger.debug("Job %s: claim failed (already taken or not QUEUED)", job_id)
        return None

    # Fetch the full job object
    job = db.query(Job).filter(Job.id == job_id).one()

    # Log the transition event
    event = Event(
        job_id=job.id,
        from_state=JobStatus.QUEUED.value,
        to_state=JobStatus.PROCESSING.value,
        actor=f"worker:{worker_id}",
        detail="Job claimed via atomic lease",
    )
    db.add(event)
    db.flush()

    logger.info("Job %s: claimed by worker %s", job_id, worker_id)
    return job


def claim_approved_job(
    db: Session,
    job_id: UUID,
    worker_id: str,
) -> Optional[Job]:
    """Atomically lock an APPROVED job for export/write-back."""
    from sqlalchemy import update

    result = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.APPROVED,
        )
        .values(
            locked_by=worker_id,
            locked_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        .returning(Job.id)
    )
    db.flush()

    row = result.first()
    if row is None:
        return None

    job = db.query(Job).filter(Job.id == job_id).one()
    logger.info("Job %s: approved job locked by worker %s", job_id, worker_id)
    return job
