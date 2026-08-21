"""The contract position register: one entry per clause area, and the rule that builds it.

The reconciliation rule here is the heart of the system, so it is deliberately boring code with the
judgement pushed to the edge. Structure is decided by `reconcile`; compatibility is decided by an
injected judge. That split is what makes silence structural (INVARIANTS.md I1) and what lets the
whole thing be tested without a live model.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.clause import ClauseArea, Party, Verdict
from app.domain.position import Position


class CompatibilityRuling(BaseModel):
    """A judge's opinion on whether two stated positions can coexist.

    `judged_by` and `confident` exist so a verdict never overstates its own provenance. A conflict
    found by a keyword heuristic and one weighed by a model are both useful; presenting them
    identically is not.
    """

    model_config = ConfigDict(frozen=True)

    compatible: bool
    rationale: str = Field(min_length=1)
    judged_by: str = Field(min_length=1)
    # False when the judge reached its answer by not finding evidence against, rather than by
    # finding evidence for. Absence of a detected conflict is not a finding of agreement.
    confident: bool = True


class CompatibilityJudge(Protocol):
    """Decides whether two positions on the same clause area are compatible.

    Implemented by a model-backed judge in production and by deterministic fakes in tests. It is
    only ever called when *both* sides have said something — see `reconcile`.
    """

    def __call__(
        self, area: ClauseArea, buyer: Position, supplier: Position
    ) -> CompatibilityRuling: ...


class JudgeConsultedOnSilence(AssertionError):
    """Raised if a judge is consulted when one side has no position.

    This should be unreachable. It exists because I1 is the invariant most likely to be quietly
    broken by a later refactor, and a loud failure beats a plausible-looking wrong verdict.
    """


class RegisterEntry(BaseModel):
    """One clause area, both sides' positions, and the verdict between them.

    Invariants enforced at construction:
      * at least one side must have a position — an entry nobody addressed is not an entry
      * exactly one position implies `SILENCE`, always
      * two positions imply `AGREE` or `CONFLICT`, never `SILENCE`
    """

    model_config = ConfigDict(frozen=True)

    area: ClauseArea
    verdict: Verdict
    rationale: str = Field(min_length=1)
    buyer_position: Position | None = None
    supplier_position: Position | None = None
    # Who decided. `None` for SILENCE, because no judge was consulted — see DECISIONS.md D1. That
    # null is itself evidence the structural path was taken.
    judged_by: str | None = None
    confident: bool = True

    @model_validator(mode="after")
    def _verdict_must_match_the_evidence(self) -> RegisterEntry:
        present = [p for p in (self.buyer_position, self.supplier_position) if p is not None]

        if not present:
            raise ValueError(
                f"register entry for {self.area} has no position from either side; "
                "areas neither document addresses are reported separately, not as entries"
            )

        for position in present:
            if position.area != self.area:
                raise ValueError(
                    f"entry for {self.area} carries a position about {position.area}"
                )

        if len(present) == 1 and self.verdict is not Verdict.SILENCE:
            raise ValueError(
                f"only one side states a position on {self.area}, so the verdict must be "
                f"{Verdict.SILENCE!s} — got {self.verdict!s}. Reporting a one-sided term as "
                f"{self.verdict!s} would present a gap as an outcome."
            )

        if len(present) == 2 and self.verdict is Verdict.SILENCE:
            raise ValueError(
                f"both sides state a position on {self.area}, so the verdict cannot be "
                f"{Verdict.SILENCE!s}"
            )

        return self

    @property
    def silent_party(self) -> Party | None:
        """Which side said nothing, when the verdict is silence."""
        if self.verdict is not Verdict.SILENCE:
            return None
        return Party.BUYER if self.buyer_position is None else Party.SUPPLIER

    @property
    def needs_review(self) -> bool:
        """Whether a human has to look at this entry before it commits.

        Conflicts and silences always need review. So does an unconfident `AGREE`: a judge that
        merely failed to find a contradiction has not established that the parties agree, and
        committing that as settled would be the system claiming more than it knows.
        """
        return self.verdict.is_actionable or not self.confident

    def content_hash(self) -> str:
        """Stable hash of everything a reader would see.

        Used to prove that an incremental update left untouched entries byte-identical
        (INVARIANTS.md I5). Canonical JSON with sorted keys, so the hash depends on content and not
        on field ordering or serialisation incidentals.
        """
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reconcile(
    area: ClauseArea,
    buyer: Position | None,
    supplier: Position | None,
    judge: CompatibilityJudge,
) -> RegisterEntry | None:
    """Compare the two sides on one clause area.

    Returns `None` when neither document addresses the area at all. That is a real gap, but it is a
    fact about the pile rather than a disagreement within it, so the caller reports it separately
    instead of inventing an entry with nothing in it.

    The judge is consulted **only** when both sides have stated a position. When one side is silent
    there is nothing to compare, and asking a model to compare a clause against an absence is an
    invitation to hallucinate an answer.
    """
    if buyer is None and supplier is None:
        return None

    if buyer is None or supplier is None:
        stated = buyer or supplier
        assert stated is not None  # narrowed by the branch above
        missing = Party.SUPPLIER if supplier is None else Party.BUYER
        return RegisterEntry(
            area=area,
            verdict=Verdict.SILENCE,
            rationale=(
                f"The {stated.party} document states a position on {area.label.lower()}; "
                f"the {missing} document does not address it."
            ),
            buyer_position=buyer,
            supplier_position=supplier,
        )

    ruling = judge(area=area, buyer=buyer, supplier=supplier)
    return RegisterEntry(
        area=area,
        verdict=Verdict.AGREE if ruling.compatible else Verdict.CONFLICT,
        rationale=ruling.rationale,
        buyer_position=buyer,
        supplier_position=supplier,
        judged_by=ruling.judged_by,
        confident=ruling.confident,
    )
