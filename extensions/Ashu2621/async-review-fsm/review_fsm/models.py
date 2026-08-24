from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ReviewState(StrEnum):
    IDLE = "IDLE"
    SUBMITTED = "SUBMITTED"
    WORKING = "WORKING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    PARTIALLY_DECIDED = "PARTIALLY_DECIDED"
    RESUMING = "RESUMING"
    AWAITING_CONTINUE = "AWAITING_CONTINUE"
    PARTIAL_STOPPED = "PARTIAL_STOPPED"
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


TERMINAL_STATES = frozenset(
    {
        ReviewState.PARTIAL_STOPPED,
        ReviewState.FINISHED,
        ReviewState.FAILED,
        ReviewState.CANCELLED,
    }
)


class ReviewEventType(StrEnum):
    SUBMIT = "SUBMIT"
    PROVIDER_STARTED = "PROVIDER_STARTED"
    POLL_TICK = "POLL_TICK"
    PROPOSALS_READY = "PROPOSALS_READY"
    DECISIONS_RECORDED = "DECISIONS_RECORDED"
    PROVIDER_RESUMED = "PROVIDER_RESUMED"
    CONTINUE_REQUIRED = "CONTINUE_REQUIRED"
    CONTINUE = "CONTINUE"
    STOP = "STOP"
    PROVIDER_COMPLETED = "PROVIDER_COMPLETED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    CANCEL = "CANCEL"
    RECOVERY_NEEDED = "RECOVERY_NEEDED"
    RECONCILED = "RECONCILED"


class CommandType(StrEnum):
    START_JOB = "START_JOB"
    POLL_JOB = "POLL_JOB"
    PERSIST_PROPOSALS = "PERSIST_PROPOSALS"
    SUBMIT_DECISIONS = "SUBMIT_DECISIONS"
    SUBMIT_CONTINUE = "SUBMIT_CONTINUE"
    SUBMIT_STOP = "SUBMIT_STOP"
    CANCEL_JOB = "CANCEL_JOB"
    RECONCILE_JOB = "RECONCILE_JOB"
    PUBLISH_STATE = "PUBLISH_STATE"


class ReviewSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: str = Field(min_length=1, max_length=128)
    state: ReviewState = ReviewState.IDLE
    version: int = Field(default=1, ge=1)
    processed_event_ids: frozenset[str] = Field(default_factory=frozenset)
    context: dict[str, JsonValue] = Field(default_factory=dict)


class ReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=128)
    batch_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)
    type: ReviewEventType
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: CommandType
    idempotency_key: str = Field(min_length=1, max_length=256)
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class TransitionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: ReviewSnapshot
    commands: tuple[Command, ...] = ()
    audit_facts: dict[str, JsonValue] = Field(default_factory=dict)
    duplicate: bool = False
