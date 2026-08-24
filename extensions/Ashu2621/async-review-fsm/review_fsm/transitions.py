from dataclasses import dataclass

from review_fsm.models import CommandType, ReviewEventType, ReviewState


@dataclass(frozen=True, slots=True)
class TransitionRule:
    sources: frozenset[ReviewState]
    event: ReviewEventType
    targets: tuple[ReviewState, ...]
    commands: tuple[CommandType, ...]
    condition: str | None = None


NON_TERMINAL_STATES = frozenset(
    state
    for state in ReviewState
    if state
    not in {
        ReviewState.PARTIAL_STOPPED,
        ReviewState.FINISHED,
        ReviewState.FAILED,
        ReviewState.CANCELLED,
    }
)


TRANSITION_RULES: tuple[TransitionRule, ...] = (
    TransitionRule(
        frozenset({ReviewState.IDLE}),
        ReviewEventType.SUBMIT,
        (ReviewState.SUBMITTED,),
        (CommandType.START_JOB,),
    ),
    TransitionRule(
        frozenset({ReviewState.SUBMITTED}),
        ReviewEventType.PROVIDER_STARTED,
        (ReviewState.WORKING,),
        (CommandType.POLL_JOB,),
    ),
    TransitionRule(
        frozenset({ReviewState.WORKING, ReviewState.RESUMING}),
        ReviewEventType.POLL_TICK,
        (ReviewState.WORKING, ReviewState.RESUMING),
        (CommandType.POLL_JOB,),
        "remain in the current state",
    ),
    TransitionRule(
        frozenset({ReviewState.WORKING, ReviewState.RESUMING}),
        ReviewEventType.PROPOSALS_READY,
        (ReviewState.AWAITING_REVIEW,),
        (CommandType.PERSIST_PROPOSALS, CommandType.PUBLISH_STATE),
    ),
    TransitionRule(
        frozenset({ReviewState.WORKING, ReviewState.RESUMING}),
        ReviewEventType.CONTINUE_REQUIRED,
        (ReviewState.AWAITING_CONTINUE,),
        (CommandType.PUBLISH_STATE,),
    ),
    TransitionRule(
        frozenset({ReviewState.AWAITING_REVIEW, ReviewState.PARTIALLY_DECIDED}),
        ReviewEventType.DECISIONS_RECORDED,
        (ReviewState.PARTIALLY_DECIDED, ReviewState.RESUMING),
        (CommandType.SUBMIT_DECISIONS, CommandType.PUBLISH_STATE),
        "remaining_count > 0 selects PARTIALLY_DECIDED",
    ),
    TransitionRule(
        frozenset({ReviewState.PARTIALLY_DECIDED}),
        ReviewEventType.PROVIDER_RESUMED,
        (ReviewState.RESUMING,),
        (CommandType.POLL_JOB,),
    ),
    TransitionRule(
        frozenset({ReviewState.AWAITING_CONTINUE}),
        ReviewEventType.CONTINUE,
        (ReviewState.RESUMING,),
        (CommandType.SUBMIT_CONTINUE,),
    ),
    TransitionRule(
        frozenset({ReviewState.AWAITING_CONTINUE}),
        ReviewEventType.STOP,
        (ReviewState.PARTIAL_STOPPED,),
        (CommandType.SUBMIT_STOP, CommandType.PUBLISH_STATE),
    ),
    TransitionRule(
        frozenset({ReviewState.WORKING, ReviewState.RESUMING}),
        ReviewEventType.PROVIDER_COMPLETED,
        (ReviewState.FINISHED,),
        (CommandType.PUBLISH_STATE,),
    ),
    TransitionRule(
        frozenset(
            {
                ReviewState.SUBMITTED,
                ReviewState.WORKING,
                ReviewState.RESUMING,
                ReviewState.RECOVERY_REQUIRED,
            }
        ),
        ReviewEventType.PROVIDER_FAILED,
        (ReviewState.FAILED,),
        (CommandType.PUBLISH_STATE,),
    ),
    TransitionRule(
        NON_TERMINAL_STATES,
        ReviewEventType.CANCEL,
        (ReviewState.CANCELLED,),
        (CommandType.CANCEL_JOB,),
    ),
    TransitionRule(
        NON_TERMINAL_STATES - {ReviewState.RECOVERY_REQUIRED},
        ReviewEventType.RECOVERY_NEEDED,
        (ReviewState.RECOVERY_REQUIRED,),
        (CommandType.RECONCILE_JOB,),
    ),
    TransitionRule(
        frozenset({ReviewState.RECOVERY_REQUIRED}),
        ReviewEventType.RECONCILED,
        (
            ReviewState.WORKING,
            ReviewState.AWAITING_REVIEW,
            ReviewState.PARTIALLY_DECIDED,
            ReviewState.AWAITING_CONTINUE,
            ReviewState.RESUMING,
            ReviewState.FINISHED,
            ReviewState.FAILED,
        ),
        (CommandType.PUBLISH_STATE,),
        "target comes from the durable provider job",
    ),
)


def rule_for(state: ReviewState, event: ReviewEventType) -> TransitionRule | None:
    return next(
        (rule for rule in TRANSITION_RULES if rule.event is event and state in rule.sources),
        None,
    )


def diagram_edges() -> tuple[tuple[ReviewState, ReviewEventType, ReviewState], ...]:
    edges: list[tuple[ReviewState, ReviewEventType, ReviewState]] = []
    for rule in TRANSITION_RULES:
        for source in sorted(rule.sources, key=lambda item: item.value):
            targets = (source,) if rule.event is ReviewEventType.POLL_TICK else rule.targets
            for target in targets:
                edges.append((source, rule.event, target))
    return tuple(edges)
