"""Task 2.2's audit trail -- a formal, chronological record of every
conclusion in the close package: what was concluded, from which exact
clause, whether it was independently verified, and whether it required
judgement. Makes NO new LLM call and asserts NO new claim independent of
what drafter/analysis.py and close_package/schedule.py already produced
and verified -- this module only re-shapes already-checked data into
audit-trail form. Same "no new hallucination surface" logic as every
deterministic synthesis stage in this project (Task 1 stage 4, Task 2's
synthesize_memo).

WHY THIS IS ITS OWN MODULE, NOT PART OF THE MEMO: a revenue recognition
memo is written for someone deciding whether to trust the conclusions. An
audit trail is written for someone verifying HOW those conclusions were
reached, later, possibly by an outside auditor who never saw the original
analysis run. That's a different reader with a different question, so it
gets its own document inside the package, not folded into the memo's own
prose.
"""

from __future__ import annotations

from typing import Any

from close_package.state import AuditTrailEntry, ClosePackageState


def _obligation_entries(state: ClosePackageState) -> list[AuditTrailEntry]:
    entries: list[AuditTrailEntry] = []
    for ob in state["memo_state"]["analysis"]["performance_obligations"]:
        distinctness = "distinct" if ob["is_distinct"] else "bundled into another obligation"
        entries.append(
            {
                "category": "performance_obligation",
                "subject": ob["obligation_id"],
                "conclusion": f"{ob['description']} -- {distinctness}",
                "source_quote": ob["source_quote"],
                "citation_verified": ob["citation_verified"],
                "is_judgement": ob["is_judgement"],
                "judgement_note": ob["judgement_note"],
                "requires_human_review": ob["requires_human_review"],
            }
        )
    return entries


def _allocation_entries(state: ClosePackageState) -> list[AuditTrailEntry]:
    entries: list[AuditTrailEntry] = []
    for alloc in state["memo_state"]["analysis"]["price_allocations"]:
        entries.append(
            {
                "category": "price_allocation",
                "subject": alloc["obligation_id"],
                "conclusion": f"{alloc['allocated_amount']} (basis: {alloc['allocation_basis']})",
                "source_quote": alloc["source_quote"],
                "citation_verified": alloc["citation_verified"],
                "is_judgement": alloc["is_judgement"],
                "judgement_note": alloc["judgement_note"],
                "requires_human_review": alloc["requires_human_review"],
            }
        )
    return entries


def _timing_entries(state: ClosePackageState) -> list[AuditTrailEntry]:
    entries: list[AuditTrailEntry] = []
    for timing in state["memo_state"]["analysis"]["timing_conclusions"]:
        entries.append(
            {
                "category": "timing_conclusion",
                "subject": timing["obligation_id"],
                "conclusion": f"{timing['recognition_pattern']} -- {timing['timing_basis']}",
                "source_quote": timing["source_quote"],
                "citation_verified": timing["citation_verified"],
                "is_judgement": timing["is_judgement"],
                "judgement_note": timing["judgement_note"],
                "requires_human_review": timing["requires_human_review"],
            }
        )
    return entries


def _schedule_fact_entries(state: ClosePackageState) -> list[AuditTrailEntry]:
    entries: list[AuditTrailEntry] = []
    for fact in state["schedule"]["schedule_facts"]:
        entries.append(
            {
                "category": "schedule_fact",
                "subject": fact["obligation_id"],
                "conclusion": (
                    f"recognition period starts {fact['term_start_description']}, "
                    f"spans {fact['term_length_months']} month(s)"
                ),
                "source_quote": fact["source_quote"],
                "citation_verified": fact["citation_verified"],
                # Schedule facts are mechanical extractions (a start
                # description and a month count), not accounting
                # characterizations -- unlike is_distinct/recognition_
                # pattern, there's no judgement call being made here.
                "is_judgement": False,
                "judgement_note": "",
                "requires_human_review": fact["requires_human_review"],
            }
        )
    return entries


def build_audit_trail(state: ClosePackageState) -> dict[str, Any]:
    audit_trail = (
        _obligation_entries(state)
        + _allocation_entries(state)
        + _timing_entries(state)
        + _schedule_fact_entries(state)
    )
    return {
        "audit_trail": audit_trail,
        "stage_log": [*state.get("stage_log", []), "build_audit_trail"],
    }
