"""Turns a validated DraftRequest into the literal content block sent to SuperDocs.

The core rule this module exists to enforce: every number that ends up in the
final document was computed here, in plain Python, from numbers the engineer
supplied — never by the model. The chat instruction tells the AI to lay this
block into the uploaded template's structure and formatting, not to recompute
or re-derive any of it.
"""
from __future__ import annotations

import html

from .models import DraftRequest


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def render_fmea_table(req: DraftRequest) -> str:
    rows = []
    for fm in req.failure_modes:
        rpn = fm.rpn()
        rpn_cell = str(rpn) if rpn is not None else "TBD"
        rows.append(
            "<tr>"
            f"<td>{_esc(fm.id)}</td>"
            f"<td>{_esc(fm.function)}</td>"
            f"<td>{_esc(fm.failure_mode)}</td>"
            f"<td>{_esc(fm.effect)}</td>"
            f"<td>{fm.severity if fm.severity is not None else 'TBD'}</td>"
            f"<td>{fm.occurrence if fm.occurrence is not None else 'TBD'}</td>"
            f"<td>{fm.detection if fm.detection is not None else 'TBD'}</td>"
            f"<td>{rpn_cell}</td>"
            f"<td>{_esc(fm.current_controls)}</td>"
            "</tr>"
        )
    actions_rows = []
    for a in req.actions:
        actions_rows.append(
            "<tr>"
            f"<td>{_esc(a.id)}</td>"
            f"<td>{_esc(a.failure_mode_id)}</td>"
            f"<td>{_esc(a.recommended_action)}</td>"
            f"<td>{_esc(a.responsible or 'TBD')}</td>"
            f"<td>{_esc(a.target_date or 'TBD')}</td>"
            f"<td>{_esc(a.status)}</td>"
            "</tr>"
        )

    fmea_table = (
        "<table data-role=\"fmea-table\">"
        "<thead><tr>"
        "<th>ID</th><th>Function</th><th>Failure Mode</th><th>Effect</th>"
        "<th>Severity (S)</th><th>Occurrence (O)</th><th>Detection (D)</th>"
        "<th>RPN (S&times;O&times;D)</th><th>Current Controls</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    actions_table = (
        "<table data-role=\"action-table\">"
        "<thead><tr>"
        "<th>Action ID</th><th>Failure Mode</th><th>Recommended Action</th>"
        "<th>Responsible</th><th>Target Date</th><th>Status</th>"
        "</tr></thead><tbody>" + "".join(actions_rows) + "</tbody></table>"
    )
    return fmea_table + "\n" + actions_table


def render_ppap_narrative(req: DraftRequest) -> str:
    p = req.ppap
    if p is None:
        return ""
    level = p.submission_level if p.submission_level is not None else "TBD"
    return (
        f"<h2>PPAP Submission — {_esc(p.part_name)} ({_esc(p.part_number)})</h2>"
        f"<p><b>Supplier:</b> {_esc(p.supplier_name)} &nbsp; <b>Customer:</b> {_esc(p.customer_name)} "
        f"&nbsp; <b>Submission Level:</b> {level}</p>"
        f"<h3>Reason for Submission</h3><p>{_esc(p.reason_for_submission)}</p>"
        f"<h3>Design Records</h3><p>{_esc(p.design_records_summary or 'TBD')}</p>"
        f"<h3>Process Flow Diagram</h3><p>{_esc(p.process_flow_summary or 'TBD')}</p>"
        f"<h3>Control Plan</h3><p>{_esc(p.control_plan_summary or 'TBD')}</p>"
        f"<h3>Dimensional Results</h3><p>{_esc(p.dimensional_results_summary or 'TBD')}</p>"
        f"<h3>Material / Performance Test Results</h3><p>{_esc(p.material_performance_summary or 'TBD')}</p>"
    )


def render_8d_narrative(req: DraftRequest) -> str:
    d = req.eightd
    if d is None:
        return ""
    fields = [
        ("D1 — Team", d.d1_team),
        ("D2 — Problem Description", d.d2_problem_description),
        ("D3 — Containment Actions", d.d3_containment_actions),
        ("D4 — Root Cause", d.d4_root_cause),
        ("D5 — Permanent Corrective Actions", d.d5_permanent_corrective_actions),
        ("D6 — Implementation & Verification", d.d6_implementation_verification),
        ("D7 — Prevent Recurrence", d.d7_prevent_recurrence),
        ("D8 — Team Recognition", d.d8_team_recognition),
    ]
    parts = [f"<h2>8D Report — {_esc(req.item_or_process)}</h2>"]
    for title, value in fields:
        parts.append(f"<h3>{_esc(title)}</h3><p>{_esc(value) if value else 'TBD'}</p>")
    return "".join(parts)


def render_content_block(req: DraftRequest) -> str:
    """The full literal content block for this document_type. This is what
    gets embedded verbatim in the chat instruction — see build_instruction()."""
    parts = []
    if req.document_type in ("fmea", "combined"):
        parts.append("<h2>FMEA — " + _esc(req.item_or_process) + "</h2>")
        parts.append(render_fmea_table(req))
    if req.document_type in ("ppap", "combined"):
        parts.append(render_ppap_narrative(req))
    if req.document_type in ("8d", "combined"):
        parts.append(render_8d_narrative(req))
    return "\n".join(p for p in parts if p)


def build_instruction(req: DraftRequest) -> str:
    """The natural-language instruction sent alongside the content block.

    Deliberately explicit about the one behavior this whole build exists to
    guarantee: the numbers are final, computed, and not to be touched.
    """
    content = render_content_block(req)
    return (
        f"This document is the customer's own template for {req.customer_name}. "
        f"Populate it with the following supplier-quality content for "
        f"'{req.item_or_process}', prepared by {req.engineer_name}. "
        "Fit the content into the template's existing section structure, headings, "
        "and formatting — reorganize placement to match the template's layout, but do not "
        "change the template's overall style. "
        "The table below already has every numeric value (Severity, Occurrence, Detection, "
        "and the computed RPN) filled in — insert it verbatim, as an HTML table, without "
        "recalculating, rounding, or altering any number in it. Cells marked 'TBD' are "
        "genuinely unknown; keep them as 'TBD' in the output rather than filling in a guess.\n\n"
        f"--- CONTENT TO INSERT ---\n{content}\n--- END CONTENT ---"
    )
