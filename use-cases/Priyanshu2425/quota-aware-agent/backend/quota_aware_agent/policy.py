"""The rules this agent runs under, as data rather than as three arguments.

`budget.py` prices work and fits it to a number. What it must never do is
decide *how much* to hold back, *how many* steps a loop may take, or what to do
when the work does not fit — those are choices an operator makes, and they
belong somewhere an operator can read them.

They were arguments to the constructor, which is fine until somebody has to
answer *why did it stop?* — and the honest answer is a rule with a name, not a
number that was too low. That distinction is the whole of this module. From the
research: an engineer described putting in a hard cap, having it fire twice on
runs that were fine, and raising the number until it stopped firing. A limit
whose only feedback is "I stopped" trains the person to disable it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class WhenItDoesNotFit(str, Enum):
    """What to do with work that will not fit in the remaining allowance."""

    #: Do the highest-severity part that fits and name what was left out.
    DEGRADE = "degrade"
    #: Do none of it. For a caller who would rather have nothing than a subset.
    REFUSE = "refuse"


class StopReason(str, Enum):
    """Why a run ended. Every one of these is a rule, and every rule can say
    what it was protecting — which is what makes it arguable rather than just
    obstructive."""

    COMPLETED = "completed"
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATION_EXHAUSTED = "ration_exhausted"
    RESERVE_FLOOR = "reserve_floor"
    NOTHING_FITS = "nothing_fits"
    REFUSED_PARTIAL = "refused_partial"
    SAMPLE_BOUND = "sample_bound"
    ALREADY_APPLIED = "already_applied"
    STARTED_AND_UNKNOWN = "started_and_unknown"

    def explain(self) -> str:
        return _WHY[self]


_WHY: dict[StopReason, str] = {
    StopReason.COMPLETED: "All of the requested work was done.",
    StopReason.QUOTA_EXHAUSTED: (
        "SuperDocs itself reported the allowance exhausted. That is the "
        "platform's own signal and the only authoritative one — our arithmetic "
        "never overrules it, and raising a number here would not help."
    ),
    StopReason.RATION_EXHAUSTED: (
        "The shared relay lends the SuperDocs key under a daily ration and "
        "today's is spent. This is a second ceiling sitting under the account's "
        "own allowance, which may well be untouched — so the remedy is "
        "different: set SUPERDOCS_API_KEY to your own key and the ration stops "
        "applying, or wait for 00:00 UTC. The refused call was not billed, by "
        "either of them."
    ),
    StopReason.RESERVE_FLOOR: (
        "The reserve was reached. It exists so the work already done can still "
        "be exported: exports are free, so holding one operation back costs "
        "nothing and guarantees you end up with a file rather than a session."
    ),
    StopReason.NOTHING_FITS: (
        "None of the requested work fits inside the remaining allowance. "
        "Nothing was uploaded and nothing was billed, so there is no "
        "half-edited document to clean up."
    ),
    StopReason.REFUSED_PARTIAL: (
        "Only part of the work fits, and this policy is set to refuse a partial "
        "run rather than deliver a subset. Set when_it_does_not_fit=DEGRADE to "
        "take the part that fits."
    ),
    StopReason.SAMPLE_BOUND: (
        "The small-sample bound was reached. Anything that loops needs a "
        "stopping rule; this one is yours and it did what you asked."
    ),
    StopReason.ALREADY_APPLIED: (
        "This step was applied by an earlier run and was not repeated. "
        "SuperDocs has no idempotency on billable writes, so repeating it would "
        "have been charged again."
    ),
    StopReason.STARTED_AND_UNKNOWN: (
        "An earlier run started this step and never learned whether it "
        "finished. It was not repeated, because repeating it might be charged "
        "twice and might apply the same edit twice. It needs a person to look "
        "at the document."
    ),
}


@dataclass(frozen=True)
class Policy:
    """How much to hold back, how far to go, and what to do when it will not fit.

    Frozen, so a policy that was read at the start of a run is the policy the
    run ended under. `with_` returns a modified copy rather than mutating, for
    the same reason.
    """

    #: Operations never spent on new edits, so finished work can always be
    #: exported. Exports are free, so this costs the user nothing.
    reserve: int = 1
    #: The small-sample bound. None means "as many as were asked for".
    max_steps: int | None = None
    when_it_does_not_fit: WhenItDoesNotFit = WhenItDoesNotFit.DEGRADE

    def __post_init__(self) -> None:
        if self.reserve < 0:
            raise ValueError("a reserve cannot be negative")
        if self.max_steps is not None and self.max_steps < 1:
            raise ValueError("a sample bound of zero would do nothing and say nothing")

    def spendable(self, remaining_ops: int) -> int:
        """What may be spent on new edits, which is not what is left."""
        return max(0, remaining_ops - self.reserve)

    def bound(self, steps: list) -> tuple[list, bool]:
        """Apply the sample bound. Returns the steps and whether it bit."""
        if self.max_steps is None or len(steps) <= self.max_steps:
            return list(steps), False
        return list(steps[: self.max_steps]), True

    def with_(self, **changes) -> "Policy":
        return replace(self, **changes)

    def describe(self) -> str:
        parts = [
            f"Holding back {self.reserve} operation(s) so finished work can "
            "always be exported."
        ]
        if self.max_steps is not None:
            parts.append(f"At most {self.max_steps} step(s) in one run.")
        parts.append(
            "Work that does not fit is sized down by severity and what is left "
            "out is named."
            if self.when_it_does_not_fit is WhenItDoesNotFit.DEGRADE
            else "Work that does not fit is refused whole rather than delivered "
            "in part."
        )
        return " ".join(parts)
