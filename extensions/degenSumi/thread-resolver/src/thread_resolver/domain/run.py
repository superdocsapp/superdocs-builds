"""State of one run, and the stages it moves through.

State is a value: every transition returns a new object rather than mutating the
old one. A run is written to a store after each stage, so a resumed run must
begin from exactly the state that was written, and an earlier stage holding a
mutable reference into a later one would break that.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from thread_resolver.domain.models import Decision, Disposition, ReviewItem


class Stage(StrEnum):
    """Stages in order. A run resumes at the stage it last completed."""

    DISCOVER = "discover"
    """Read threads out of the document."""

    CLASSIFY = "classify"
    """Decide what each open thread is."""

    DRAFT = "draft"
    """Ask the editing service for a change, for actionable threads only."""

    REVIEW = "review"
    """Put every item in front of a person."""

    APPLY = "apply"
    """Write approved changes into the document."""

    CLOSE = "close"
    """Mark approved threads resolved."""

    DONE = "done"


STAGE_ORDER: tuple[Stage, ...] = (
    Stage.DISCOVER,
    Stage.CLASSIFY,
    Stage.DRAFT,
    Stage.REVIEW,
    Stage.APPLY,
    Stage.CLOSE,
    Stage.DONE,
)


@dataclass(frozen=True, slots=True)
class StageTiming:
    stage: Stage
    seconds: float


@dataclass(frozen=True, slots=True)
class RunState:
    """Everything needed to continue a run that was interrupted."""

    run_id: str
    document_name: str
    stage: Stage = Stage.DISCOVER
    items: tuple[ReviewItem, ...] = ()
    session_id: str | None = None
    timings: tuple[StageTiming, ...] = ()
    operations_spent: int = 0

    def advance_to(self, stage: Stage) -> RunState:
        return replace(self, stage=stage)

    def with_items(self, items: tuple[ReviewItem, ...]) -> RunState:
        return replace(self, items=items)

    def with_session(self, session_id: str) -> RunState:
        return replace(self, session_id=session_id)

    def with_timing(self, stage: Stage, seconds: float) -> RunState:
        return replace(self, timings=(*self.timings, StageTiming(stage, seconds)))

    def spending(self, operations: int) -> RunState:
        return replace(self, operations_spent=self.operations_spent + operations)

    def replace_item(self, item: ReviewItem) -> RunState:
        """Swap one item by thread id, leaving the order and the rest intact."""
        updated = tuple(
            item if existing.thread_id == item.thread_id else existing for existing in self.items
        )
        return replace(self, items=updated)

    # -- views over the items ----------------------------------------------

    @property
    def actionable(self) -> tuple[ReviewItem, ...]:
        return tuple(
            item for item in self.items if item.classification.disposition is Disposition.ACTIONABLE
        )

    @property
    def needs_drafting(self) -> tuple[ReviewItem, ...]:
        """Actionable items that do not yet carry a proposal.

        Filtering on what is already done is what makes a resumed run continue
        rather than repeat, and is what stops a second operation being spent on
        a thread already drafted.
        """
        return tuple(item for item in self.actionable if not item.proposed_edits)

    @property
    def undecided(self) -> tuple[ReviewItem, ...]:
        return tuple(item for item in self.items if not item.is_decided)

    @property
    def approved(self) -> tuple[ReviewItem, ...]:
        return tuple(item for item in self.items if item.decision is Decision.APPROVE)

    @property
    def dismissed(self) -> tuple[ReviewItem, ...]:
        """Items a person read and finished with. The thread stays open regardless."""
        return tuple(item for item in self.items if item.decision is Decision.REJECT)

    @property
    def deferred(self) -> tuple[ReviewItem, ...]:
        return tuple(item for item in self.items if item.decision is Decision.DEFER)

    @property
    def closable(self) -> tuple[ReviewItem, ...]:
        """Items whose approval should mark their thread resolved."""
        return tuple(item for item in self.items if item.closes_thread)

    def counts(self) -> dict[str, int]:
        """Tally by disposition, for the run report."""
        tally: dict[str, int] = {}
        for item in self.items:
            key = str(item.classification.disposition)
            tally[key] = tally.get(key, 0) + 1
        return tally

    @property
    def total_seconds(self) -> float:
        return sum(timing.seconds for timing in self.timings)
