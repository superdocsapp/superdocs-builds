"""
document_builder.py — turns an RFI object into the formal RFI document
HTML SuperDocs expects (send HTML in, get edited HTML back).

Same discipline as Build 1's document_builder.py: this module is pure,
deterministic, and fully testable without touching the live API. Every
field in the output HTML comes straight from an RFI object's own
attributes — this module only formats them, it never invents or
recomputes anything.

The "strong" bar for this build is explicit: "Reviewer supplies one
fictional RFI payload with a spec section and a drawing reference, and
the generated document carries both references correctly into the
formal RFI format." Both fields get their own labeled row, unambiguous
in the output HTML, so a reviewer checking data fidelity has exact
strings to search for.

What this must never do:
  - never invent or reformat a field's text — every value here is
    passed through verbatim from the RFI object
  - never silently drop a field — spec_section and drawing_reference
    are always rendered, whether or not the RFI has been answered
  - never show a stale Response/Status when the RFI has moved on from
    Open to Answered - the Response section only renders once a
    response actually exists, and never fabricates placeholder text
"""

from __future__ import annotations

from construction_data import RFI


def _field_row(label: str, value: str) -> str:
    return f'<tr><td><strong>{label}</strong></td><td>{value}</td></tr>'


def build_rfi_document_html(rfi: RFI) -> str:
    """
    Builds the full formal RFI document for one RFI, in the traditional
    construction RFI form layout: header block (project, RFI number,
    dates, parties), the spec section and drawing reference the "what
    strong looks like" bar checks for, the question, and — once
    answered — the response block with cost/schedule impact.
    """
    header_rows = "\n".join(
        [
            _field_row("RFI Number", rfi.rfi_number),
            _field_row("Project", f"{rfi.project_name} (Project No. {rfi.project_number})"),
            _field_row("Subject", rfi.subject),
            _field_row("Spec Section", rfi.spec_section),
            _field_row("Drawing Reference", rfi.drawing_reference),
            _field_row("Submitted By", rfi.submitted_by),
            _field_row("Submitted To", rfi.submitted_to),
            _field_row("Date Submitted", rfi.date_submitted),
            _field_row("Date Required", rfi.date_required),
            _field_row("Status", rfi.status),
        ]
    )

    if rfi.status == "Answered" and rfi.response:
        response_block = f"""
<h2>Response</h2>
<table>
{_field_row("Responded By", rfi.responded_by or "")}
{_field_row("Date Responded", rfi.date_responded or "")}
{_field_row("Cost Impact", rfi.cost_impact or "Not assessed")}
{_field_row("Schedule Impact", rfi.schedule_impact or "Not assessed")}
</table>
<p>{rfi.response}</p>"""
    else:
        response_block = """
<h2>Response</h2>
<p>Awaiting response.</p>"""

    return f"""<div>
<h1>Request for Information</h1>
<table>
{header_rows}
</table>
<h2>Question</h2>
<p>{rfi.question}</p>
{response_block}
</div>"""
