"""Compatibility judges, and the fallback chain between them.

Two requirements pull against each other here.

*Graceful degradation*: "when a model call or an external dependency fails, your system falls back
and keeps running instead of dying with it."

*Never bluffs*: a verdict reached by a keyword heuristic must never be presented as though a model
weighed the clauses. So every ruling names the judge that produced it, and that name travels all the
way to the register entry and into the review UI. Degrading is allowed; degrading silently is not.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.clause import ClauseArea
from app.domain.position import Position
from app.domain.register import CompatibilityJudge, CompatibilityRuling
from app.extraction.quarantine import render_position_for_judge

# Pairs of mutually exclusive commitments. Data, not code: a new contradiction is a row here.
# Each entry is (label, left pattern, right pattern) — a match on opposite sides means conflict.
CONTRADICTIONS: dict[ClauseArea, tuple[tuple[str, str, str], ...]] = {
    ClauseArea.LIABILITY: (
        (
            "unlimited versus capped liability",
            r"unlimited|no cap|without limit",
            r"cap(?:ped)?|limited to|not exceed",
        ),
    ),
    ClauseArea.DELIVERY: (
        ("incompatible incoterms", r"\bddp\b|delivered duty paid", r"\bexw\b|ex works|\bfca\b"),
    ),
    ClauseArea.PAYMENT: (
        (
            "incompatible payment terms",
            r"net\s*30|within 30 days|payable within 30",
            r"net\s*(?:45|60|90)|within (?:45|60|90) days|payable within (?:45|60|90)",
        ),
    ),
    ClauseArea.GOVERNING_LAW: (
        (
            "competing jurisdictions",
            r"laws of england|english law",
            r"laws of (?:the state of )?(?!england)\w+",
        ),
    ),
    ClauseArea.TITLE_AND_RISK: (
        (
            "title passes at different points",
            r"on delivery|upon delivery",
            r"on payment|upon payment|retention of title",
        ),
    ),
}


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _cited_text(position: Position) -> str:
    return " ".join(c.quote for c in position.citations)


class HeuristicJudge:
    """Offline judge. Deterministic, explainable, and openly limited.

    It exists so the whole system runs, and is demonstrable, with no API key — which is what makes
    the test suite meaningful and a fresh clone runnable. It is not pretending to be reasoning: it
    reports itself as `heuristic` and states which contradiction rule fired.
    """

    name = "heuristic"

    def __call__(
        self, *, area: ClauseArea, buyer: Position, supplier: Position
    ) -> CompatibilityRuling:
        left, right = _cited_text(buyer), _cited_text(supplier)

        for label, a, b in CONTRADICTIONS.get(area, ()):
            if (_matches(a, left) and _matches(b, right)) or (
                _matches(b, left) and _matches(a, right)
            ):
                return CompatibilityRuling(
                    compatible=False,
                    rationale=f"{label}: the two documents take opposing positions.",
                    judged_by=self.name,
                    confident=True,
                )

        # No rule fired. That is not evidence of agreement — it is absence of evidence, and the
        # difference matters. The ruling says compatible so the run continues, but flags itself as
        # unconfident so the review UI can mark it for a human rather than presenting it as settled.
        return CompatibilityRuling(
            compatible=True,
            rationale=(
                "No contradiction rule matched these clauses. This is the absence of a detected "
                "conflict, not a positive finding of agreement."
            ),
            judged_by=self.name,
            confident=False,
        )


class ModelJudge:
    """Model-backed judge. Reads only quarantined text (INVARIANTS.md I4).

    The call itself is supplied by the caller so this class stays testable and provider-agnostic;
    `complete` takes a prompt and returns text.
    """

    name = "model"

    def __init__(self, complete, model_name: str) -> None:
        self._complete = complete
        self.name = f"model:{model_name}"

    def __call__(
        self, *, area: ClauseArea, buyer: Position, supplier: Position
    ) -> CompatibilityRuling:
        prompt = (
            "Decide whether these two contractual positions can both hold at once.\n"
            "Answer with COMPATIBLE or CONFLICT on the first line, then one sentence of reasoning.\n"
            "Judge only on the extracts given. If they do not give you enough to decide, say "
            "INSUFFICIENT.\n\n"
            f"--- Buyer ---\n{render_position_for_judge(buyer)}\n\n"
            f"--- Supplier ---\n{render_position_for_judge(supplier)}\n"
        )
        raw = self._complete(prompt).strip()
        head, _, reasoning = raw.partition("\n")
        verdict = head.strip().upper()

        if verdict.startswith("INSUFFICIENT"):
            # Refusing to decide is a legitimate answer and must not be coerced into one.
            raise InsufficientEvidence(reasoning.strip() or raw)

        return CompatibilityRuling(
            compatible=verdict.startswith("COMPATIBLE"),
            rationale=reasoning.strip() or raw,
            judged_by=self.name,
            confident=True,
        )


class InsufficientEvidence(RuntimeError):
    """The judge declined to decide. Escalates rather than being turned into a guess."""


class FallbackJudge:
    """Try each judge in order; use the first that returns a ruling.

    Every fallback is recorded in `degradations` so a run can report honestly that it ran degraded.
    A system that quietly downgraded its own reasoning and reported the same confident verdict would
    be bluffing in the most damaging possible way.
    """

    def __init__(self, judges: Sequence[CompatibilityJudge]) -> None:
        if not judges:
            raise ValueError("a fallback chain needs at least one judge")
        self._judges = list(judges)
        self.degradations: list[str] = []

    def __call__(
        self, *, area: ClauseArea, buyer: Position, supplier: Position
    ) -> CompatibilityRuling:
        last_error: Exception | None = None

        for index, judge in enumerate(self._judges):
            try:
                return judge(area=area, buyer=buyer, supplier=supplier)
            except InsufficientEvidence:
                # Not a failure of the judge — a refusal to guess. Do not paper over it with a
                # weaker judge; it goes to a person.
                raise
            except Exception as exc:  # noqa: BLE001 - any provider failure degrades, none crash
                last_error = exc
                name = getattr(judge, "name", judge.__class__.__name__)
                self.degradations.append(
                    f"{area}: judge {name!r} failed ({exc.__class__.__name__}: {exc}); "
                    f"falling back to the next judge"
                )
                if index == len(self._judges) - 1:
                    raise AllJudgesFailed(
                        f"every judge failed for {area}; last error was {exc!r}"
                    ) from exc

        raise AllJudgesFailed(f"no judge produced a ruling for {area}") from last_error


class AllJudgesFailed(RuntimeError):
    """Nothing in the chain could rule. The stage escalates rather than inventing a verdict."""
