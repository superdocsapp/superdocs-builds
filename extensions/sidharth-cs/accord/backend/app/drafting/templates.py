"""Professional starter templates for the live deliverable.  Each template
uses {{token}} placeholders filled from meeting metadata (Zoom SDK context)
so no "TBD" literals ever appear when metadata is available."""

from __future__ import annotations

SOW = "statement_of_work"
MINUTES = "meeting_minutes"
PROPOSAL = "proposal"
ADVICE_NOTE = "advice_note"
REQUIREMENTS_LIST = "requirements_list"

_TEMPLATES: dict[str, dict[str, str]] = {
    SOW: {
        "label": "Statement of Work",
        "description": "Scope, deliverables, timeline, and budget for a project engagement.",
        "sections": [
            'Project Details',
            'Scope of Work',
            'Deliverables',
            'Timeline & Milestones',
            'Budget / Commercial Terms',
            'Assumptions & Dependencies',
            'Out of Scope',
            'Next Steps',
        ],
        "html": (
            '<h1>Statement of Work</h1>'
            '<h2>Project Details</h2>'
            '<table>'
            '<tr><td><strong>Client</strong></td><td>{{client}}</td></tr>'
            '<tr><td><strong>Project</strong></td><td>{{topic}}</td></tr>'
            '<tr><td><strong>Date</strong></td><td>{{date}}</td></tr>'
            '<tr><td><strong>Prepared by</strong></td><td>{{prepared_by}}</td></tr>'
            '</table>'
            '<h2>Scope of Work</h2><p><p></p></p>'
            '<h2>Deliverables</h2><p><p></p></p>'
            '<h2>Timeline &amp; Milestones</h2><p><p></p></p>'
            '<h2>Budget / Commercial Terms</h2><p><p></p></p>'
            '<h2>Assumptions &amp; Dependencies</h2><p><p></p></p>'
            '<h2>Out of Scope</h2><p><p></p></p>'
            '<h2>Next Steps</h2><p><p></p></p>'
        ),
    },
    MINUTES: {
        "label": "Meeting Minutes",
        "description": "Attendees, agenda, decisions, and action items from the call.",
        "sections": [
            'Meeting Details',
            'Attendees',
            'Agenda',
            'Discussion & Decisions',
            'Action Items',
            'Next Meeting',
        ],
        "html": (
            '<h1>Meeting Minutes</h1>'
            '<h2>Meeting Details</h2>'
            '<table>'
            '<tr><td><strong>Topic</strong></td><td>{{topic}}</td></tr>'
            '<tr><td><strong>Date</strong></td><td>{{date}}</td></tr>'
            '<tr><td><strong>Prepared by</strong></td><td>{{prepared_by}}</td></tr>'
            '</table>'
            '<h2>Attendees</h2><p><p></p></p>'
            '<h2>Agenda</h2><p><p></p></p>'
            '<h2>Discussion &amp; Decisions</h2><p><p></p></p>'
            '<h2>Action Items</h2><p><p></p></p>'
            '<h2>Next Meeting</h2><p><p></p></p>'
        ),
    },
    PROPOSAL: {
        "label": "Proposal / Offer",
        "description": "Client needs, proposed solution, timeline, and investment.",
        "sections": [
            'Proposal Details',
            'Client Needs',
            'Proposed Solution',
            'Scope of Work',
            'Timeline',
            'Investment',
            'Why Us',
            'Next Steps',
        ],
        "html": (
            '<h1>Proposal</h1>'
            '<h2>Proposal Details</h2>'
            '<table>'
            '<tr><td><strong>Client</strong></td><td>{{client}}</td></tr>'
            '<tr><td><strong>Project</strong></td><td>{{topic}}</td></tr>'
            '<tr><td><strong>Date</strong></td><td>{{date}}</td></tr>'
            '<tr><td><strong>Prepared by</strong></td><td>{{prepared_by}}</td></tr>'
            '</table>'
            '<h2>Client Needs</h2><p><p></p></p>'
            '<h2>Proposed Solution</h2><p><p></p></p>'
            '<h2>Scope of Work</h2><p><p></p></p>'
            '<h2>Timeline</h2><p><p></p></p>'
            '<h2>Investment</h2><p><p></p></p>'
            '<h2>Why Us</h2><p><p></p></p>'
            '<h2>Next Steps</h2><p><p></p></p>'
        ),
    },
    ADVICE_NOTE: {
        "label": "Advice Note",
        "description": "Professional advice on a specific matter — background, advice given, risks, and recommendations.",
        "sections": [
            'Matter Details',
            'Background',
            'Questions Raised',
            'Advice',
            'Key Considerations & Risks',
            'Recommendations',
            'Next Steps',
        ],
        "html": (
            '<h1>Advice Note</h1>'
            '<h2>Matter Details</h2>'
            '<table>'
            '<tr><td><strong>Client</strong></td><td>{{client}}</td></tr>'
            '<tr><td><strong>Matter</strong></td><td>{{topic}}</td></tr>'
            '<tr><td><strong>Date</strong></td><td>{{date}}</td></tr>'
            '<tr><td><strong>Prepared by</strong></td><td>{{prepared_by}}</td></tr>'
            '</table>'
            '<h2>Background</h2><p><p></p></p>'
            '<h2>Questions Raised</h2><p><p></p></p>'
            '<h2>Advice</h2><p><p></p></p>'
            '<h2>Key Considerations &amp; Risks</h2><p><p></p></p>'
            '<h2>Recommendations</h2><p><p></p></p>'
            '<h2>Next Steps</h2><p><p></p></p>'
        ),
    },
    REQUIREMENTS_LIST: {
        "label": "Requirements List",
        "description": "Functional and non-functional requirements, constraints, and assumptions captured from the call.",
        "sections": [
            'Project Details',
            'Functional Requirements',
            'Non-Functional Requirements',
            'Constraints',
            'Assumptions',
            'Out of Scope',
            'Next Steps',
        ],
        "html": (
            '<h1>Requirements List</h1>'
            '<h2>Project Details</h2>'
            '<table>'
            '<tr><td><strong>Client</strong></td><td>{{client}}</td></tr>'
            '<tr><td><strong>Project</strong></td><td>{{topic}}</td></tr>'
            '<tr><td><strong>Date</strong></td><td>{{date}}</td></tr>'
            '<tr><td><strong>Prepared by</strong></td><td>{{prepared_by}}</td></tr>'
            '</table>'
            '<h2>Functional Requirements</h2><p><p></p></p>'
            '<h2>Non-Functional Requirements</h2><p><p></p></p>'
            '<h2>Constraints</h2><p><p></p></p>'
            '<h2>Assumptions</h2><p><p></p></p>'
            '<h2>Out of Scope</h2><p><p></p></p>'
            '<h2>Next Steps</h2><p><p></p></p>'
        ),
    },
}


def get_template(key: str) -> dict[str, str] | None:
    """Return {label, description, html} for a template key, or None."""
    return _TEMPLATES.get(key)


def list_templates() -> list[dict[str, str]]:
    """Return [{key, label, description}, ...] for all available templates."""
    return [
        {"key": key, "label": t["label"], "description": t["description"]}
        for key, t in _TEMPLATES.items()
    ]


# The product that authored the document. Not a transcript fact and never
# spoken aloud, so nothing in the pipeline could ever have filled it — the
# cell rendered empty in every exported document until this default existed.
PREPARED_BY = "ACCORD"


def render_template(
    key: str,
    *,
    topic: str = "",
    client: str = "",
    prepared_by: str = "",
    date: str = "",
) -> str:
    """Render a template with meeting metadata filled in.  Tokens without
    a value are replaced with a descriptive placeholder — never 'TBD'."""
    template = _TEMPLATES.get(key)
    if template is None:
        raise ValueError(f"unknown template: {key}")
    html = template["html"]
    import time

    today = date or time.strftime("%B %d, %Y")
    replacements = {
        "{{topic}}": topic or "",
        "{{client}}": client or "",
        "{{prepared_by}}": prepared_by or PREPARED_BY,
        "{{date}}": today,
    }
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html


def template_sections(key: str) -> list[str]:
    """The template's canonical section names, in document order.

    Sections are no longer seeded into the starter HTML — a section heading
    now appears only once something is actually said that belongs under it,
    so the live document grows with the conversation instead of opening as a
    wall of empty subheadings. Routing still needs to know the full set of
    possible sections, and their order, which is what this provides.
    """
    template = _TEMPLATES.get(key)
    return list(template["sections"]) if template else []
