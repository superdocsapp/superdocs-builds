from collections.abc import Iterable

from review_fsm.errors import ReviewTransitionError
from review_fsm.models import (
    TERMINAL_STATES,
    Command,
    CommandType,
    ReviewEvent,
    ReviewEventType,
    ReviewSnapshot,
    ReviewState,
    TransitionResult,
)
from review_fsm.transitions import rule_for


def _command(event: ReviewEvent, command_type: CommandType) -> Command:
    return Command(
        type=command_type,
        idempotency_key=f"{event.batch_id}:{event.event_id}:{command_type.value}",
        payload=event.payload,
    )


def _transition(
    snapshot: ReviewSnapshot,
    event: ReviewEvent,
    next_state: ReviewState,
    command_types: Iterable[CommandType] = (),
) -> TransitionResult:
    context = dict(snapshot.context)
    context.update(event.payload)
    next_snapshot = snapshot.model_copy(
        update={
            "state": next_state,
            "version": snapshot.version + 1,
            "processed_event_ids": snapshot.processed_event_ids | {event.event_id},
            "context": context,
        }
    )
    return TransitionResult(
        snapshot=next_snapshot,
        commands=tuple(_command(event, command_type) for command_type in command_types),
        audit_facts={
            "event_id": event.event_id,
            "event_type": event.type.value,
            "from_state": snapshot.state.value,
            "to_state": next_state.value,
        },
    )


def reduce(snapshot: ReviewSnapshot, event: ReviewEvent) -> TransitionResult:
    """Apply one event without I/O, clocks or randomness."""

    if event.batch_id != snapshot.batch_id:
        raise ReviewTransitionError(
            code="BATCH_CONTEXT_MISMATCH",
            message="The event belongs to a different review batch.",
        )
    if event.event_id in snapshot.processed_event_ids:
        return TransitionResult(snapshot=snapshot, duplicate=True)
    if event.expected_version != snapshot.version:
        raise ReviewTransitionError(
            code="BATCH_VERSION_CONFLICT",
            message="The review batch version is stale.",
        )
    if snapshot.state in TERMINAL_STATES:
        raise ReviewTransitionError(
            code="TERMINAL_STATE",
            message="A terminal review state cannot transition.",
        )

    state = snapshot.state
    event_type = event.type

    rule = rule_for(state, event_type)
    if rule is None:
        raise ReviewTransitionError(
            code="INVALID_TRANSITION",
            message=f"{event_type.value} is invalid from {state.value}.",
        )

    if event_type is ReviewEventType.DECISIONS_RECORDED:
        remaining_count = event.payload.get("remaining_count", 0)
        if not isinstance(remaining_count, int) or remaining_count < 0:
            raise ReviewTransitionError(
                code="INVALID_REMAINING_COUNT",
                message="remaining_count must be a non-negative integer.",
            )
        next_state = (
            ReviewState.PARTIALLY_DECIDED if remaining_count > 0 else ReviewState.RESUMING
        )
        return _transition(snapshot, event, next_state, rule.commands)
    if event_type is ReviewEventType.RECONCILED:
        recovered_state = event.payload.get("recovered_state")
        try:
            next_state = ReviewState(str(recovered_state))
        except ValueError as exc:
            raise ReviewTransitionError(
                code="INVALID_RECOVERED_STATE",
                message="The reconciliation result contains an invalid state.",
            ) from exc
        if next_state not in rule.targets:
            raise ReviewTransitionError(
                code="UNSAFE_RECOVERED_STATE",
                message="Reconciliation returned a state that cannot be restored safely.",
            )
        return _transition(snapshot, event, next_state, rule.commands)
    next_state = state if event_type is ReviewEventType.POLL_TICK else rule.targets[0]
    return _transition(snapshot, event, next_state, rule.commands)
