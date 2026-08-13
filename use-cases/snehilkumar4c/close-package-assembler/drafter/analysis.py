"""Task 2's citation-verification layer -- the drafter's equivalent of
pipeline/extract.py and pipeline/reconcile.py (Task 1).

THE CORE GUARANTEE, same as Task 1's: `core.llm.LLMClient.analyze_
revenue_recognition()` asks the model for a citation on every obligation,
allocation, and timing conclusion, but nothing here is trusted just
because the model returned it. Every `source_quote` is independently
verified against the actual contract text via `core.citations.
quote_is_verifiable()` -- the SAME function Task 1 uses, not a
reimplementation -- before `citation_verified` is set. An unverifiable
citation is never discarded; it's kept and flagged
`requires_human_review=True`, exactly like Task 1's stages 2 and 3.

Also enforces the card's own "what strong looks like" requirement that
"areas of judgement are flagged as judgement, not stated as fact":
`is_judgement`/`judgement_note` are read straight through from the model's
response (the model is the one deciding whether something required
interpretation), but a judgement call with no citation support gets the
same `requires_human_review` treatment as any other unverified claim --
being a judgement call doesn't exempt it from needing a real anchor in the
contract text.
"""

from __future__ import annotations

from typing import Any

from core.citations import quote_is_verifiable
from core.llm import LLMClient
from core.logging import get_logger
from drafter.state import (
    DrafterState,
    JudgementNote,
    MemoAnalysis,
    PerformanceObligation,
    PriceAllocation,
    RecognitionPattern,
    TimingConclusion,
)

logger = get_logger(__name__)

_VALID_RECOGNITION_PATTERNS = {"point_in_time", "over_time"}


def _verify_obligations(
    raw_items: list[dict[str, Any]], contract_text: str
) -> list[PerformanceObligation]:
    obligations: list[PerformanceObligation] = []
    for item in raw_items:
        if not isinstance(item, dict):
            # Same defensive posture as Task 1's pipeline/extract.py,
            # /reconcile.py, /examine.py: a real, observed API anomaly
            # (a large tool-call response's nested array mis-serialized),
            # not a hypothetical. Never let a malformed item crash the
            # whole analysis pass.
            logger.warning("malformed_obligation_skipped", item=repr(item)[:200])
            continue

        verified = quote_is_verifiable(item.get("source_quote", ""), contract_text)
        is_judgement = bool(item.get("is_judgement", False))
        obligation: PerformanceObligation = {
            "obligation_id": item.get("obligation_id", ""),
            "description": item.get("description", ""),
            "source_quote": item.get("source_quote", ""),
            "citation_verified": verified,
            "is_distinct": bool(item.get("is_distinct", True)),
            "is_judgement": is_judgement,
            "judgement_note": item.get("judgement_note", ""),
            "requires_human_review": not verified,
        }
        obligations.append(obligation)

        log_fields = {"obligation_id": obligation["obligation_id"]}
        if verified:
            logger.info("obligation_extracted", **log_fields)
        else:
            logger.warning(
                "unverifiable_obligation_citation",
                source_quote=obligation["source_quote"],
                **log_fields,
            )
    return obligations


def _verify_allocations(
    raw_items: list[dict[str, Any]], contract_text: str
) -> list[PriceAllocation]:
    allocations: list[PriceAllocation] = []
    for item in raw_items:
        if not isinstance(item, dict):
            logger.warning("malformed_price_allocation_skipped", item=repr(item)[:200])
            continue

        verified = quote_is_verifiable(item.get("source_quote", ""), contract_text)
        allocation: PriceAllocation = {
            "obligation_id": item.get("obligation_id", ""),
            "allocated_amount": item.get("allocated_amount", ""),
            "allocation_basis": item.get("allocation_basis", ""),
            "source_quote": item.get("source_quote", ""),
            "citation_verified": verified,
            "is_judgement": bool(item.get("is_judgement", False)),
            "judgement_note": item.get("judgement_note", ""),
            "requires_human_review": not verified,
        }
        allocations.append(allocation)

        if not verified:
            logger.warning(
                "unverifiable_allocation_citation",
                obligation_id=allocation["obligation_id"],
                source_quote=allocation["source_quote"],
            )
    return allocations


def _verify_timing(
    raw_items: list[dict[str, Any]], contract_text: str
) -> list[TimingConclusion]:
    timings: list[TimingConclusion] = []
    for item in raw_items:
        if not isinstance(item, dict):
            logger.warning("malformed_timing_conclusion_skipped", item=repr(item)[:200])
            continue

        raw_pattern = item.get("recognition_pattern", "")
        # A pattern outside the two valid values is itself untrustworthy --
        # never silently coerce it to one arbitrarily; treat it the same
        # as an unverifiable citation (flagged for human review) rather
        # than guessing which of the two the model "meant."
        pattern_valid = raw_pattern in _VALID_RECOGNITION_PATTERNS
        recognition_pattern: RecognitionPattern = (
            raw_pattern if pattern_valid else "point_in_time"  # placeholder, always flagged below
        )
        verified = pattern_valid and quote_is_verifiable(
            item.get("source_quote", ""), contract_text
        )
        timing: TimingConclusion = {
            "obligation_id": item.get("obligation_id", ""),
            "recognition_pattern": recognition_pattern,
            "timing_basis": item.get("timing_basis", ""),
            "source_quote": item.get("source_quote", ""),
            "citation_verified": verified,
            "is_judgement": bool(item.get("is_judgement", False)),
            "judgement_note": item.get("judgement_note", ""),
            "requires_human_review": not verified,
        }
        timings.append(timing)

        if not verified:
            logger.warning(
                "unverifiable_timing_citation",
                obligation_id=timing["obligation_id"],
                pattern_valid=pattern_valid,
                source_quote=timing["source_quote"],
            )
    return timings


def _build_judgement_notes(analysis: MemoAnalysis) -> list[JudgementNote]:
    """Derived FROM the per-record is_judgement flags, not an independent
    second source of truth -- see drafter/state.py's module docstring for
    why this matters."""
    notes: list[JudgementNote] = []
    for ob in analysis["performance_obligations"]:
        if ob["is_judgement"]:
            notes.append(
                {
                    "topic": f"Performance obligation: {ob['obligation_id']}",
                    "obligation_id": ob["obligation_id"],
                    "explanation": ob["judgement_note"],
                }
            )
    for alloc in analysis["price_allocations"]:
        if alloc["is_judgement"]:
            notes.append(
                {
                    "topic": f"Price allocation: {alloc['obligation_id']}",
                    "obligation_id": alloc["obligation_id"],
                    "explanation": alloc["judgement_note"],
                }
            )
    for timing in analysis["timing_conclusions"]:
        if timing["is_judgement"]:
            notes.append(
                {
                    "topic": f"Recognition timing: {timing['obligation_id']}",
                    "obligation_id": timing["obligation_id"],
                    "explanation": timing["judgement_note"],
                }
            )
    return notes


def analyze_contract(state: DrafterState, llm: LLMClient) -> dict[str, Any]:
    """The drafter's equivalent of pipeline/extract.py + reconcile.py
    combined into one LLM call (see core/llm.py's analyze_revenue_
    recognition docstring for why one call, not three)."""
    contract_text = state["contract_text"]
    raw = llm.analyze_revenue_recognition(contract_text)

    analysis: MemoAnalysis = {
        "contract_filename": state["contract_filename"],
        "performance_obligations": _verify_obligations(
            raw.get("performance_obligations", []), contract_text
        ),
        "price_allocations": _verify_allocations(
            raw.get("price_allocations", []), contract_text
        ),
        "timing_conclusions": _verify_timing(raw.get("timing_conclusions", []), contract_text),
    }

    return {
        "analysis": analysis,
        "judgement_notes": _build_judgement_notes(analysis),
        "stage_log": [*state.get("stage_log", []), "analyze_contract"],
    }
