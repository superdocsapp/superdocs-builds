"""Deterministic memo assembly -- Task 2's equivalent of pipeline/
synthesize.py (Task 1 stage 4). Makes NO new LLM call, for the same
reason stage 4 doesn't: by the time analysis reaches this stage, every
citation has already been independently verified against the contract
text (drafter/analysis.py). Assembling the memo from that already-checked
data is pure, deterministic code -- no new hallucination surface, because
this stage never asks a model anything.

WHAT GETS SURFACED, AND WHY NOTHING IS SILENTLY DROPPED: unlike Task 1's
vendor register (where an unverified fact is safely just left out -- a
register with fewer entries than possible is still correct, just
incomplete), a revenue recognition memo's reader needs to know about EVERY
obligation/allocation/timing conclusion the analysis found, including the
ones that couldn't be verified -- silently omitting one from the memo
would hide a real gap from the accountant who has to sign off on it.
So every item is rendered into the memo's narrative, and unverified items
get an explicit inline flag PLUS a listing in the dedicated "Items
Requiring Verification" section, rather than being dropped.

Areas of judgement get their own section too, straight from
judgement_notes (drafter/analysis.py already derived these from the
per-record is_judgement flags -- this stage just renders them, it does
not re-decide what counts as a judgement call).
"""

from __future__ import annotations

from typing import Any

from core.logging import get_logger
from drafter.state import (
    DrafterState,
    JudgementNote,
    MemoAnalysis,
    PerformanceObligation,
    PriceAllocation,
    TimingConclusion,
)

logger = get_logger(__name__)


def _review_flag(requires_human_review: bool) -> str:
    return (
        ' <span style="color:#b45309;font-weight:bold;">'
        "[NEEDS HUMAN REVIEW -- citation could not be verified against "
        "the source contract]</span>"
        if requires_human_review
        else ""
    )


def _render_obligation(ob: PerformanceObligation) -> str:
    distinctness = "a distinct performance obligation" if ob["is_distinct"] else "bundled into another obligation"
    judgement = f" <em>(judgement call: {ob['judgement_note']})</em>" if ob["is_judgement"] else ""
    return (
        f"<li><strong>{ob['obligation_id']}</strong> -- {ob['description']} "
        f"({distinctness}).{judgement}"
        f'<br><span style="color:#555;">Source: &ldquo;{ob["source_quote"]}&rdquo;</span>'
        f"{_review_flag(ob['requires_human_review'])}</li>"
    )


def _render_allocation(alloc: PriceAllocation) -> str:
    judgement = (
        f" <em>(judgement call: {alloc['judgement_note']})</em>" if alloc["is_judgement"] else ""
    )
    return (
        f"<li><strong>{alloc['obligation_id']}</strong>: {alloc['allocated_amount']} "
        f"(basis: {alloc['allocation_basis']}).{judgement}"
        f'<br><span style="color:#555;">Source: &ldquo;{alloc["source_quote"]}&rdquo;</span>'
        f"{_review_flag(alloc['requires_human_review'])}</li>"
    )


def _render_timing(timing: TimingConclusion) -> str:
    pattern_label = "recognized over time" if timing["recognition_pattern"] == "over_time" else "recognized at a point in time"
    judgement = (
        f" <em>(judgement call: {timing['judgement_note']})</em>" if timing["is_judgement"] else ""
    )
    return (
        f"<li><strong>{timing['obligation_id']}</strong>: revenue is {pattern_label} "
        f"-- {timing['timing_basis']}.{judgement}"
        f'<br><span style="color:#555;">Source: &ldquo;{timing["source_quote"]}&rdquo;</span>'
        f"{_review_flag(timing['requires_human_review'])}</li>"
    )


def _render_judgement_notes(notes: list[JudgementNote]) -> str:
    if not notes:
        # An honest, complete result -- same posture as Task 1's compliance
        # stage: "a clean corpus... is the rarest output in this industry:
        # an honest report of no findings." No judgement calls required is
        # a real, reportable outcome, not a gap.
        return "<p>No areas of judgement were identified in this analysis.</p>"
    items = "\n".join(f"<li><strong>{n['topic']}</strong>: {n['explanation']}</li>" for n in notes)
    return f"<ul>\n{items}\n</ul>"


def _collect_unverified(analysis: MemoAnalysis) -> list[str]:
    unverified: list[str] = []
    for ob in analysis["performance_obligations"]:
        if ob["requires_human_review"]:
            unverified.append(f"Performance obligation &ldquo;{ob['obligation_id']}&rdquo;")
    for alloc in analysis["price_allocations"]:
        if alloc["requires_human_review"]:
            unverified.append(f"Price allocation for &ldquo;{alloc['obligation_id']}&rdquo;")
    for timing in analysis["timing_conclusions"]:
        if timing["requires_human_review"]:
            unverified.append(f"Recognition timing for &ldquo;{timing['obligation_id']}&rdquo;")
    return unverified


def _render_unverified_section(unverified: list[str]) -> str:
    if not unverified:
        return (
            "<p>All conclusions in this memo are backed by citations "
            "independently verified against the source contract.</p>"
        )
    items = "\n".join(f"<li>{u}</li>" for u in unverified)
    return (
        "<p><strong>The following conclusions could not be independently "
        "verified against the source contract text and require manual "
        "confirmation before this memo is relied upon:</strong></p>"
        f"<ul>\n{items}\n</ul>"
    )


def render_memo_html(analysis: MemoAnalysis, judgement_notes: list[JudgementNote]) -> str:
    obligations_html = (
        "\n".join(_render_obligation(o) for o in analysis["performance_obligations"])
        or "<li>No performance obligations were identified.</li>"
    )
    allocations_html = (
        "\n".join(_render_allocation(a) for a in analysis["price_allocations"])
        or "<li>No price allocation could be determined.</li>"
    )
    timing_html = (
        "\n".join(_render_timing(t) for t in analysis["timing_conclusions"])
        or "<li>No timing conclusions were determined.</li>"
    )
    unverified = _collect_unverified(analysis)

    return f"""<h1>Revenue Recognition Memo</h1>
<p><strong>Contract:</strong> {analysis["contract_filename"]}</p>

<h2>1. Performance Obligations</h2>
<ul>
{obligations_html}
</ul>

<h2>2. Transaction Price and Allocation</h2>
<ul>
{allocations_html}
</ul>

<h2>3. Timing of Revenue Recognition</h2>
<ul>
{timing_html}
</ul>

<h2>4. Areas of Judgement</h2>
{_render_judgement_notes(judgement_notes)}

<h2>5. Items Requiring Verification</h2>
{_render_unverified_section(unverified)}
"""


def synthesize_memo(state: DrafterState) -> dict[str, Any]:
    """LangGraph/orchestration node function -- no LLM parameter, because
    this stage makes no LLM call at all (same shape as pipeline/
    synthesize.py's own node function)."""
    memo_html = render_memo_html(state["analysis"], state["judgement_notes"])
    logger.info(
        "memo_synthesized",
        contract_filename=state["contract_filename"],
        obligation_count=len(state["analysis"]["performance_obligations"]),
        judgement_count=len(state["judgement_notes"]),
        unverified_count=len(_collect_unverified(state["analysis"])),
    )
    return {
        "memo_html": memo_html,
        "stage_log": [*state.get("stage_log", []), "synthesize_memo"],
    }
