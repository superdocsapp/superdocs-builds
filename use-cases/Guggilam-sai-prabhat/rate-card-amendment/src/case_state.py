"""The nine-state lifecycle for one partner contract's amendment case.

State transitions are enforced by `transition()` — an illegal transition
raises `IllegalStateTransition` naming the current state, the attempted
target, and why it's disallowed, rather than silently mutating state.
"""

from __future__ import annotations

from enum import Enum


class CaseState(str, Enum):
    PENDING = "pending"
    ANALYSING = "analysing"
    REQUIRES_REVIEW = "requires_review"
    BLOCKED = "blocked"
    PROPOSED = "proposed"
    PARTIALLY_APPROVED = "partially_approved"
    APPROVED = "approved"
    EXPORTED = "exported"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.PENDING: frozenset({CaseState.ANALYSING, CaseState.FAILED}),
    CaseState.ANALYSING: frozenset(
        {
            CaseState.REQUIRES_REVIEW,
            CaseState.BLOCKED,
            CaseState.PROPOSED,
            # A SuperDocs job can complete with zero pending changes (e.g.
            # the rates already matched, so no edit was needed) without ever
            # passing through PROPOSED — that is a legitimate direct path to
            # APPROVED, not an error.
            CaseState.APPROVED,
            CaseState.FAILED,
        }
    ),
    CaseState.REQUIRES_REVIEW: frozenset({CaseState.FAILED}),
    CaseState.BLOCKED: frozenset({CaseState.FAILED}),
    CaseState.PROPOSED: frozenset(
        {CaseState.PARTIALLY_APPROVED, CaseState.APPROVED, CaseState.BLOCKED, CaseState.FAILED}
    ),
    CaseState.PARTIALLY_APPROVED: frozenset(
        {CaseState.PARTIALLY_APPROVED, CaseState.APPROVED, CaseState.BLOCKED, CaseState.FAILED}
    ),
    CaseState.APPROVED: frozenset({CaseState.EXPORTED, CaseState.FAILED}),
    CaseState.EXPORTED: frozenset(),
    CaseState.FAILED: frozenset({CaseState.ANALYSING, CaseState.PROPOSED}),
}


class IllegalStateTransition(Exception):
    def __init__(self, current: CaseState, target: CaseState) -> None:
        self.what = f"cannot transition case from '{current.value}' to '{target.value}'"
        self.likely_cause = (
            "the caller attempted an operation out of sequence for this case's current lifecycle stage"
        )
        self.next_action = (
            f"only transitions {sorted(s.value for s in _ALLOWED_TRANSITIONS.get(current, frozenset()))} "
            f"are valid from '{current.value}'; re-fetch the case's current state before retrying"
        )
        super().__init__(self.what)

    def to_dict(self) -> dict[str, str]:
        return {"what": self.what, "likely_cause": self.likely_cause, "next_action": self.next_action}


def transition(current: CaseState, target: CaseState) -> CaseState:
    """Validate and return the new state, or raise `IllegalStateTransition`."""

    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise IllegalStateTransition(current, target)
    return target


TERMINAL_STATES = frozenset({CaseState.BLOCKED, CaseState.REQUIRES_REVIEW, CaseState.EXPORTED})
