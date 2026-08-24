from dataclasses import dataclass

from docrelay.domain.enums import SyncRunState


class IllegalStateTransition(ValueError):
    """Raised when code attempts a transition outside the locked run policy."""


TERMINAL_STATES = frozenset(
    {
        SyncRunState.SUCCEEDED,
        SyncRunState.CONFLICT,
        SyncRunState.UNSUPPORTED,
        SyncRunState.SKIPPED,
        SyncRunState.EXPIRED,
        SyncRunState.COMMIT_OUTCOME_UNKNOWN,
        SyncRunState.VERIFICATION_FAILED,
        SyncRunState.FAILED,
        SyncRunState.CANCELLED,
    }
)

_ALLOWED_TRANSITIONS: dict[SyncRunState, frozenset[SyncRunState]] = {
    SyncRunState.QUEUED: frozenset({SyncRunState.BASELINING, SyncRunState.CANCELLED}),
    SyncRunState.BASELINING: frozenset(
        {
            SyncRunState.EDITING,
            SyncRunState.CONFLICT,
            SyncRunState.UNSUPPORTED,
            SyncRunState.SKIPPED,
            SyncRunState.EXPIRED,
            SyncRunState.FAILED,
            SyncRunState.CANCELLED,
        }
    ),
    SyncRunState.EDITING: frozenset(
        {
            SyncRunState.AWAITING_REVIEW,
            SyncRunState.REVIEWED_EXPORT_READY,
            SyncRunState.READY_TO_COMMIT,
            SyncRunState.UNSUPPORTED,
            SyncRunState.SKIPPED,
            SyncRunState.EXPIRED,
            SyncRunState.FAILED,
            SyncRunState.CANCELLED,
        }
    ),
    SyncRunState.AWAITING_REVIEW: frozenset(
        {
            SyncRunState.EDITING,
            SyncRunState.READY_TO_COMMIT,
            SyncRunState.UNSUPPORTED,
            SyncRunState.EXPIRED,
            SyncRunState.FAILED,
            SyncRunState.CANCELLED,
        }
    ),
    SyncRunState.REVIEWED_EXPORT_READY: frozenset(
        {
            SyncRunState.READY_TO_COMMIT,
            SyncRunState.UNSUPPORTED,
            SyncRunState.EXPIRED,
            SyncRunState.FAILED,
            SyncRunState.CANCELLED,
        }
    ),
    SyncRunState.READY_TO_COMMIT: frozenset(
        {
            SyncRunState.PREVIEW_READY,
            SyncRunState.COMMITTING,
            SyncRunState.CONFLICT,
            SyncRunState.UNSUPPORTED,
            SyncRunState.EXPIRED,
            SyncRunState.FAILED,
            SyncRunState.CANCELLED,
        }
    ),
    SyncRunState.PREVIEW_READY: frozenset(
        {
            SyncRunState.COMMITTING,
            SyncRunState.CONFLICT,
            SyncRunState.EXPIRED,
            SyncRunState.CANCELLED,
        }
    ),
    SyncRunState.COMMITTING: frozenset(
        {
            SyncRunState.VERIFYING,
            SyncRunState.CONFLICT,
            SyncRunState.COMMIT_OUTCOME_UNKNOWN,
            SyncRunState.FAILED,
        }
    ),
    SyncRunState.VERIFYING: frozenset(
        {
            SyncRunState.SUCCEEDED,
            SyncRunState.VERIFICATION_FAILED,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class StateTransition:
    from_state: SyncRunState
    to_state: SyncRunState


def allowed_targets(state: SyncRunState) -> frozenset[SyncRunState]:
    return _ALLOWED_TRANSITIONS.get(state, frozenset())


def is_terminal(state: SyncRunState) -> bool:
    return state in TERMINAL_STATES


def require_transition(from_state: SyncRunState, to_state: SyncRunState) -> StateTransition:
    if to_state not in allowed_targets(from_state):
        raise IllegalStateTransition(f"illegal SyncRun transition: {from_state} -> {to_state}")
    return StateTransition(from_state=from_state, to_state=to_state)
