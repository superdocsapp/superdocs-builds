"""Deterministic close-package assembly -- Task 2.2's equivalent of
drafter/synthesize.py (which is itself Task 1 stage 4's pattern). Makes
NO new LLM call: by the time this stage runs, the memo has already been
rendered (drafter/synthesize.py), the schedule has already been extracted
and computed (close_package/schedule.py), and the audit trail has already
been built (close_package/audit_trail.py). This stage's only job is to
combine those three already-produced HTML/data pieces into one package
document -- pure string formatting, no new hallucination surface.

WHY A SCHEDULE TABLE AND AN AUDIT-TRAIL TABLE, NOT JUST THE MEMO PROSE:
the memo (section 1-5, from drafter/synthesize.py) answers "what did we
conclude and why." The schedule answers a different, mechanical question
("how much revenue lands in which period") that a close process needs in
tabular form, not prose. The audit trail answers a third question ("how
would an outside reviewer verify each conclusion, later, without redoing
the analysis"). Three different readers' questions, so three sections,
not one blended narrative -- same principle documented in
close_package/audit_trail.py's own module docstring.

Consistent with drafter/synthesize.py: every schedule entry and every
audit-trail entry is rendered, including ones flagged
requires_human_review -- nothing is silently dropped from the package
just because it couldn't be fully verified or computed. A flagged row is
surfaced with an explicit inline marker, the same visual language as
drafter/synthesize.py's _review_flag.
"""

from __future__ import annotations

from typing import Any

from close_package.state import AuditTrailEntry, ClosePackageState, ScheduleEntry
from core.logging import get_logger

logger = get_logger(__name__)


def _review_flag(requires_human_review: bool) -> str:
    return (
        ' <span style="color:#b45309;font-weight:bold;">[NEEDS HUMAN REVIEW]</span>'
        if requires_human_review
        else ""
    )


def _render_schedule_row(entry: ScheduleEntry) -> str:
    return (
        "<tr>"
        f"<td>{entry['obligation_id']}</td>"
        f"<td>{entry['period_label']}</td>"
        f"<td>{entry['recognized_amount']}</td>"
        f"<td>{entry['basis']}</td>"
        f"<td>{'Yes' if entry['requires_human_review'] else 'No'}{_review_flag(entry['requires_human_review'])}</td>"
        "</tr>"
    )


def render_schedule_html(entries: list[ScheduleEntry]) -> str:
    if not entries:
        return "<p>No schedule entries could be computed.</p>"
    rows = "\n".join(_render_schedule_row(e) for e in entries)
    return f"""<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;">
<thead>
<tr><th>Obligation</th><th>Period</th><th>Recognized Amount</th><th>Basis</th><th>Flagged</th></tr>
</thead>
<tbody>
{rows}
</tbody>
</table>"""


_CATEGORY_LABELS = {
    "performance_obligation": "Performance Obligation",
    "price_allocation": "Price Allocation",
    "timing_conclusion": "Timing Conclusion",
    "schedule_fact": "Schedule Fact",
}


def _render_audit_row(entry: AuditTrailEntry) -> str:
    judgement = f" <em>(judgement call: {entry['judgement_note']})</em>" if entry["is_judgement"] else ""
    category_label = _CATEGORY_LABELS.get(entry["category"], entry["category"])
    return (
        "<tr>"
        f"<td>{category_label}</td>"
        f"<td>{entry['subject']}</td>"
        f"<td>{entry['conclusion']}{judgement}</td>"
        f'<td>&ldquo;{entry["source_quote"]}&rdquo;</td>'
        f"<td>{'Verified' if entry['citation_verified'] else 'Unverified'}{_review_flag(entry['requires_human_review'])}</td>"
        "</tr>"
    )


def render_audit_trail_html(audit_trail: list[AuditTrailEntry]) -> str:
    if not audit_trail:
        return "<p>No audit trail entries were produced.</p>"
    rows = "\n".join(_render_audit_row(e) for e in audit_trail)
    return f"""<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;">
<thead>
<tr><th>Category</th><th>Subject</th><th>Conclusion</th><th>Source Quote</th><th>Status</th></tr>
</thead>
<tbody>
{rows}
</tbody>
</table>"""


def render_package_html(memo_html: str, schedule_entries: list[ScheduleEntry], audit_trail: list[AuditTrailEntry]) -> str:
    return f"""{memo_html}

<h2>6. Revenue Recognition Schedule</h2>
{render_schedule_html(schedule_entries)}

<h2>7. Audit Trail</h2>
{render_audit_trail_html(audit_trail)}
"""


def assemble_package(state: ClosePackageState) -> dict[str, Any]:
    """LangGraph/orchestration node function -- no LLM parameter, because
    this stage makes no LLM call at all (same shape as
    drafter/synthesize.py's synthesize_memo)."""
    package_html = render_package_html(
        state["memo_state"]["memo_html"],
        state["schedule"]["entries"],
        state["audit_trail"],
    )
    logger.info(
        "package_assembled",
        contract_filename=state["memo_state"]["contract_filename"],
        schedule_entry_count=len(state["schedule"]["entries"]),
        audit_trail_entry_count=len(state["audit_trail"]),
    )
    return {
        "package_html": package_html,
        "stage_log": [*state.get("stage_log", []), "assemble_package"],
    }
