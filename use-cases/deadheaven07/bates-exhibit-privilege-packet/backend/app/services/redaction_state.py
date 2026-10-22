"""Pure redaction state machine.

The candidate lifecycle is the core compliance invariant of the packet
builder: nothing is modified until a human reviewer approves, and rejected
candidates can never be applied. This module is deliberately free of DB and
network dependencies so the entire state machine can be proven offline.
"""

from app.domain.redaction import RedactionStatus

_TRANSITIONS: dict[RedactionStatus, set[RedactionStatus]] = {
    RedactionStatus.PROPOSED: {
        RedactionStatus.PENDING_APPROVAL,
        RedactionStatus.APPROVED,
        RedactionStatus.REJECTED,
        RedactionStatus.FAILED,
    },
    RedactionStatus.PENDING_APPROVAL: {
        RedactionStatus.APPROVED,
        RedactionStatus.REJECTED,
        RedactionStatus.PROPOSED,
        RedactionStatus.FAILED,
    },
    RedactionStatus.APPROVED: {
        RedactionStatus.APPLIED,
        RedactionStatus.REJECTED,
        RedactionStatus.FAILED,
    },
    RedactionStatus.APPLIED: {
        RedactionStatus.VERIFIED,
        RedactionStatus.FAILED,
    },
    RedactionStatus.REJECTED: set(),
    RedactionStatus.VERIFIED: set(),
    RedactionStatus.FAILED: {RedactionStatus.PROPOSED},
}

_TERMINAL = {RedactionStatus.REJECTED, RedactionStatus.VERIFIED}


class InvalidTransitionError(ValueError):
    def __init__(self, current: RedactionStatus, target: RedactionStatus):
        super().__init__(f"Invalid transition {current.value} -> {target.value}")
        self.current = current
        self.target = target


class RedactionStateMachine:
    @classmethod
    def can_transition(cls, current: RedactionStatus, target: RedactionStatus) -> bool:
        return target in _TRANSITIONS.get(current, set())

    @classmethod
    def transition(cls, current: RedactionStatus, target: RedactionStatus) -> RedactionStatus:
        if not cls.can_transition(current, target):
            raise InvalidTransitionError(current, target)
        return target

    @classmethod
    def is_terminal(cls, status: RedactionStatus) -> bool:
        return status in _TERMINAL

    @classmethod
    def allowed_targets(cls, current: RedactionStatus) -> list[RedactionStatus]:
        return sorted(_TRANSITIONS.get(current, set()), key=lambda s: s.value)
