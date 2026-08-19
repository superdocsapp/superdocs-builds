"""A review gate driven by a supplied set of decisions rather than by a person.

Two uses. Tests need a gate that answers predictably. A program driving the tool
end to end needs to make approvals explicitly, as its own call, rather than
having them happen by default.

There is deliberately no "approve everything" default. A caller that wants
blanket approval has to say so, by name, per item or by rule, so that an
unattended run can never quietly approve work nobody looked at.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from thread_resolver.domain.models import Decision, ReviewItem
from thread_resolver.ports.review import ReviewGate


class ScriptedReviewGate(ReviewGate):
    """Answers from a mapping of thread id to decision, or from a rule."""

    def __init__(
        self,
        decisions: Mapping[str, Decision] | None = None,
        *,
        rule: Callable[[ReviewItem], Decision] | None = None,
        default: Decision = Decision.DEFER,
    ) -> None:
        self._decisions = dict(decisions or {})
        self._rule = rule
        self._default = default
        self.seen: list[str] = []
        """Thread ids the gate was shown, so a test can assert nothing was hidden."""

    def present(self, items: tuple[ReviewItem, ...]) -> tuple[ReviewItem, ...]:
        decided = []
        for item in items:
            self.seen.append(item.thread_id)
            decision = self._decisions.get(item.thread_id)
            if decision is None and self._rule is not None:
                decision = self._rule(item)
            decided.append(item.with_decision(decision or self._default))
        return tuple(decided)


def approve_drafted_edits(item: ReviewItem) -> Decision:
    """Approve items carrying a proposed edit, defer everything else.

    Convenient for demonstrations and for tests. Items with no edit are deferred
    rather than approved, because approving a finding would otherwise read as
    closing a thread nobody resolved.
    """
    return Decision.APPROVE if item.proposed_edits else Decision.DEFER
