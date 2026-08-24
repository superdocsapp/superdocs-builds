from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import JsonValue

from review_fsm.models import ReviewEvent, ReviewEventType, ReviewSnapshot, ReviewState
from review_fsm.persistence import ReviewRuntime


@dataclass(frozen=True, slots=True)
class ReviewReconciliationError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class DurableJobProvider(Protocol):
    async def get_job(self, job_id: str) -> Mapping[str, JsonValue]: ...


def provider_state(job: Mapping[str, JsonValue], snapshot: ReviewSnapshot) -> ReviewState:
    status = str(job.get("status", "")).lower()
    if status in {"expired", "not_found"}:
        raise ReviewReconciliationError(
            "PROVIDER_JOB_EXPIRED",
            "The durable provider job expired; manual recovery is required.",
        )
    if status in {"failed", "cancelled", "canceled"}:
        return ReviewState.FAILED
    if status in {"completed", "complete", "finished"}:
        return ReviewState.FINISHED
    if status in {"awaiting_approval", "awaiting_review"}:
        metadata = job.get("metadata")
        kind = str(metadata.get("kind", "")) if isinstance(metadata, dict) else ""
        if kind in {"continue", "pause_and_continue", "continuation"}:
            return ReviewState.AWAITING_CONTINUE
        pending = job.get("pending_changes")
        decided = snapshot.context.get("decided_change_ids", [])
        if isinstance(pending, list) and isinstance(decided, list) and decided:
            return ReviewState.PARTIALLY_DECIDED
        return ReviewState.AWAITING_REVIEW
    if status in {"resuming"}:
        return ReviewState.RESUMING
    return ReviewState.WORKING


async def reconcile_runtime(
    runtime: ReviewRuntime,
    *,
    batch_id: str,
    provider: DurableJobProvider,
    event_prefix: str = "reconcile",
) -> ReviewSnapshot:
    snapshot = await runtime.load(batch_id)
    if snapshot is None:
        raise ReviewReconciliationError("BATCH_NOT_FOUND", "Review batch does not exist.")
    if snapshot.state is not ReviewState.RECOVERY_REQUIRED:
        result = await runtime.dispatch(
            ReviewEvent(
                event_id=f"{event_prefix}-needed-v{snapshot.version}",
                batch_id=batch_id,
                expected_version=snapshot.version,
                type=ReviewEventType.RECOVERY_NEEDED,
            )
        )
        snapshot = result.snapshot
    job_id = snapshot.context.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise ReviewReconciliationError(
            "PROVIDER_JOB_ID_MISSING",
            "The review checkpoint has no durable provider job identifier.",
        )
    job = await provider.get_job(job_id)
    recovered = provider_state(job, snapshot)
    result = await runtime.dispatch(
        ReviewEvent(
            event_id=f"{event_prefix}-complete-v{snapshot.version}",
            batch_id=batch_id,
            expected_version=snapshot.version,
            type=ReviewEventType.RECONCILED,
            payload={
                "recovered_state": recovered.value,
                "provider_status": str(job.get("status", "unknown")),
            },
        )
    )
    return result.snapshot
