"""Our decision ledger. SuperDocs' `approve` is only an actuator (Decision 33).

Measured on 2026-08-09: the product's gate is **write-only**. Before any
decision `pending_changes` listed three changes with `status: None`; after
approving one and denying another it listed the same three, still with
`status: None`. The approve call returns `{"status":"ok","batch_complete":...}`
and nothing else. There is no API answer to "what has been decided, and by whom".

So the row is ours, it is written **before** the actuator is called, and it
carries a named actor. An item is undecided exactly when it has no row - there
is no default, no pending row and no status column. A second decision on the
same item is refused unless it explicitly supersedes, and the superseded row is
kept with both actors.

The completion sentence is computed from the rows at the moment it is emitted,
never from counters, because we watched a product report "Successfully updated
all 0 sections. 2 change(s) were denied" when two had been applied and three
denied.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..errors import DecisionAlreadyRecordedError

VERBS = ("accept", "reject")


@dataclass(frozen=True)
class Decision:
    run_id: str
    step_index: int
    chunk_id: str
    verb: str
    actor: str
    reason: str
    at: str
    supersedes: str | None = None

    def __post_init__(self) -> None:
        if self.verb not in VERBS:
            raise ValueError(
                f"the vocabulary is {VERBS} and nothing else. There is no 'resolve' and no "
                f"'choose_side': a reviewer decides whether a change enters the document, not "
                f"which of two disagreeing sources is right."
            )
        if not self.actor.strip():
            raise ValueError("a decision with no actor answers nobody's question about who")


class DecisionLedger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.rows: list[Decision] = []

    def record(
        self,
        run_id: str,
        step_index: int,
        chunk_id: str,
        verb: str,
        actor: str,
        reason: str,
        supersede: bool = False,
    ) -> Decision:
        existing = self.find(run_id, step_index)
        if existing is not None and not supersede:
            raise DecisionAlreadyRecordedError(
                f"step {step_index} of run {run_id} was already decided '{existing.verb}' by "
                f"{existing.actor} at {existing.at}. Quiet replacement is the mechanism by "
                f"which a decision gets quietly dropped; pass supersede=True and both rows are "
                f"kept."
            )
        row = Decision(
            run_id=run_id,
            step_index=step_index,
            chunk_id=chunk_id,
            verb=verb,
            actor=actor,
            reason=reason,
            at=datetime.now(UTC).isoformat(timespec="seconds"),
            supersedes=existing.at if existing is not None else None,
        )
        self.rows.append(row)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(row)) + "\n")
        return row

    def find(self, run_id: str, step_index: int) -> Decision | None:
        matches = [r for r in self.rows if r.run_id == run_id and r.step_index == step_index]
        return matches[-1] if matches else None

    def decided(self, run_id: str) -> list[Decision]:
        latest: dict[int, Decision] = {}
        for row in self.rows:
            if row.run_id == run_id:
                latest[row.step_index] = row
        return [latest[k] for k in sorted(latest)]

    # No count fields anywhere: these are properties of the rows being held, so
    # the sentence cannot assert a decision that was never made (Decision 22's
    # trick, rebuilt).
    def accepted(self, run_id: str) -> int:
        return sum(1 for r in self.decided(run_id) if r.verb == "accept")

    def rejected(self, run_id: str) -> int:
        return sum(1 for r in self.decided(run_id) if r.verb == "reject")

    def describe(self, run_id: str, planned: int) -> str:
        accepted = self.accepted(run_id)
        rejected = self.rejected(run_id)
        undecided = planned - accepted - rejected
        actors = sorted({r.actor for r in self.decided(run_id)})
        return (
            f"{accepted} accepted, {rejected} rejected, {undecided} undecided of {planned} "
            f"planned change(s); decided by {', '.join(actors) or 'nobody'}"
        )
