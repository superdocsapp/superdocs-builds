"""Task 2.2's one genuinely new piece of domain logic: turns Task 2's
already-verified analysis into a period-by-period revenue recognition
schedule.

Two stages, same shape as Task 1/Task 2's own extract-then-synthesize
pattern:
1. `extract_schedule_facts()` -- ONE new, narrowly-scoped LLM call
   (core.llm.LLMClient.extract_recognition_schedule_facts), given the
   ALREADY-established obligations from Task 2's analysis as context, so
   the model's job is only to find each obligation's recognition-period
   start and length -- not to re-derive what the obligations are. Every
   citation is independently verified in code before being trusted, the
   same posture as everywhere else in this project.
2. `compute_schedule_entries()` -- pure arithmetic, ZERO new LLM calls.
   Splits each over-time obligation's already-verified allocated amount
   evenly across its verified term length; a point-in-time obligation
   gets one entry for its full amount. Anything that can't be computed
   (an unparseable dollar figure, a missing or unverified schedule fact
   for an over-time obligation) is surfaced with requires_human_review,
   never silently guessed at or dropped.
"""

from __future__ import annotations

import re
from typing import Any

from close_package.state import ClosePackageState, RevenueSchedule, ScheduleEntry, ScheduleFact
from core.citations import quote_is_verifiable
from core.llm import LLMClient
from core.logging import get_logger
from drafter.state import MemoAnalysis

logger = get_logger(__name__)

_DOLLAR_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)")


def _parse_dollar_amount(text: str) -> float | None:
    """Best-effort parse of a dollar figure out of an allocated_amount
    string like "$84,000" or "$7,000.00". Returns None (never a guessed
    number) if nothing parses -- e.g. drafter/state.py's own documented
    case of an allocation with no dollar figure at all ("included in "
    "bundle, standalone price not stated"), which is a real, expected
    shape, not a defect."""
    match = _DOLLAR_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def build_obligations_context(analysis: MemoAnalysis) -> str:
    """Formats Task 2's already-verified obligations for the schedule
    extraction prompt -- the model is given these as established facts,
    not asked to re-derive them."""
    lines = []
    timing_by_id = {t["obligation_id"]: t for t in analysis["timing_conclusions"]}
    for ob in analysis["performance_obligations"]:
        timing = timing_by_id.get(ob["obligation_id"])
        pattern = timing["recognition_pattern"] if timing else "unknown"
        lines.append(f"- {ob['obligation_id']}: {ob['description']} (recognition pattern: {pattern})")
    return "\n".join(lines)


def extract_schedule_facts(state: ClosePackageState, llm: LLMClient) -> dict[str, Any]:
    analysis = state["memo_state"]["analysis"]
    contract_text = state["memo_state"]["contract_text"]
    obligations_context = build_obligations_context(analysis)

    raw = llm.extract_recognition_schedule_facts(contract_text, obligations_context)
    known_obligation_ids = {ob["obligation_id"] for ob in analysis["performance_obligations"]}

    facts: list[ScheduleFact] = []
    for item in raw:
        if not isinstance(item, dict):
            # Same defensive posture as every other stage in this project
            # against the real, observed API/SDK response anomaly.
            logger.warning("malformed_schedule_fact_skipped", item=repr(item)[:200])
            continue

        obligation_id = item.get("obligation_id", "")
        source_quote = item.get("source_quote", "")
        verified = quote_is_verifiable(source_quote, contract_text)
        # An obligation_id that doesn't match anything from Task 2's own
        # analysis is itself untrustworthy -- never silently accept a
        # schedule fact for an obligation that was never actually
        # established.
        id_valid = obligation_id in known_obligation_ids

        fact: ScheduleFact = {
            "obligation_id": obligation_id,
            "term_start_description": item.get("term_start_description", ""),
            "term_length_months": item.get("term_length_months", 0),
            "source_quote": source_quote,
            "citation_verified": verified and id_valid,
            "requires_human_review": not (verified and id_valid),
        }
        facts.append(fact)

        if not fact["citation_verified"]:
            logger.warning(
                "unverifiable_schedule_fact",
                obligation_id=obligation_id,
                id_valid=id_valid,
                source_quote=source_quote,
            )

    return {
        "schedule": {
            "contract_filename": state["memo_state"]["contract_filename"],
            "schedule_facts": facts,
            "entries": [],  # filled in by compute_schedule_entries
        },
        "stage_log": [*state.get("stage_log", []), "extract_schedule_facts"],
    }


def compute_schedule_entries(state: ClosePackageState) -> dict[str, Any]:
    """Pure arithmetic on already-verified data -- makes NO new LLM call,
    same "no new hallucination surface" logic as Task 1's synthesize and
    Task 2's synthesize."""
    analysis = state["memo_state"]["analysis"]
    schedule_facts = state["schedule"]["schedule_facts"]

    allocation_by_id = {a["obligation_id"]: a for a in analysis["price_allocations"]}
    timing_by_id = {t["obligation_id"]: t for t in analysis["timing_conclusions"]}

    # If the model ever returns two verified schedule facts for the same
    # obligation_id, silently picking one (e.g. via a dict comprehension
    # that lets the last one win) would hide a real ambiguity from whoever
    # reads the schedule. Surfaced loudly instead; the FIRST verified fact
    # is kept, for a deterministic result.
    fact_by_id: dict[str, ScheduleFact] = {}
    for f in schedule_facts:
        if not f["citation_verified"]:
            continue
        if f["obligation_id"] in fact_by_id:
            logger.warning(
                "duplicate_verified_schedule_fact_for_obligation",
                obligation_id=f["obligation_id"],
                kept_source_quote=fact_by_id[f["obligation_id"]]["source_quote"],
                discarded_source_quote=f["source_quote"],
            )
            continue
        fact_by_id[f["obligation_id"]] = f

    entries: list[ScheduleEntry] = []
    for ob in analysis["performance_obligations"]:
        obligation_id = ob["obligation_id"]
        allocation = allocation_by_id.get(obligation_id)
        timing = timing_by_id.get(obligation_id)

        if allocation is None or timing is None:
            entries.append(
                {
                    "obligation_id": obligation_id,
                    "period_label": "N/A (no price allocation or timing conclusion)",
                    "recognized_amount": "",
                    "basis": "unknown",
                    "requires_human_review": True,
                }
            )
            continue

        amount = _parse_dollar_amount(allocation["allocated_amount"])
        if amount is None:
            entries.append(
                {
                    "obligation_id": obligation_id,
                    "period_label": "N/A (no parseable dollar amount)",
                    "recognized_amount": allocation["allocated_amount"],
                    "basis": timing["recognition_pattern"],
                    "requires_human_review": True,
                }
            )
            continue

        if timing["recognition_pattern"] == "point_in_time":
            entries.append(
                {
                    "obligation_id": obligation_id,
                    "period_label": "Period 1 (point-in-time)",
                    "recognized_amount": f"${amount:,.2f}",
                    "basis": "point_in_time",
                    "requires_human_review": False,
                }
            )
            continue

        # over_time: split evenly across the verified term length.
        fact = fact_by_id.get(obligation_id)
        term_months = fact["term_length_months"] if fact else 0
        if not fact or term_months <= 0:
            entries.append(
                {
                    "obligation_id": obligation_id,
                    "period_label": "Full term (schedule unavailable -- no verified term length)",
                    "recognized_amount": f"${amount:,.2f}",
                    "basis": "straight_line_over_time",
                    "requires_human_review": True,
                }
            )
            continue

        monthly_amount = amount / term_months
        for month in range(1, term_months + 1):
            entries.append(
                {
                    "obligation_id": obligation_id,
                    "period_label": f"Month {month} of {term_months}",
                    "recognized_amount": f"${monthly_amount:,.2f}",
                    "basis": "straight_line_over_time",
                    "requires_human_review": False,
                }
            )

    schedule: RevenueSchedule = {
        "contract_filename": state["schedule"]["contract_filename"],
        "schedule_facts": schedule_facts,
        "entries": entries,
    }
    logger.info(
        "schedule_computed",
        contract_filename=schedule["contract_filename"],
        entry_count=len(entries),
        flagged_count=sum(1 for e in entries if e["requires_human_review"]),
    )
    return {
        "schedule": schedule,
        "stage_log": [*state.get("stage_log", []), "compute_schedule_entries"],
    }
