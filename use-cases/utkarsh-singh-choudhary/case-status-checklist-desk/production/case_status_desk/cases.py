"""
Domain model for the Case Status & Document Checklist Letter Desk.

Everything here is pure, dependency-free, and unit-testable without
network access or a SuperDocs API key -- the "what does this case
actually need to say" logic is kept completely separate from the
SuperDocs client (see client.py) so the two can be tested independently.

All data is synthetic / fictional, per the SuperDocs task rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# --- Plain-language stage descriptions -------------------------------------
#
# A rule change here (new stage, or reworded language) is a data change,
# not a code change -- one dict, not a rewrite. Approved-language boundary:
# these strings are the ONLY stage language the letter is allowed to use.
# The desk never lets the AI free-write legal advice into this slot.

STAGE_LANGUAGE: dict[str, dict[str, str]] = {
    "intake": {
        "summary": "We have opened your case and are reviewing the documents you have provided so far.",
        "next": "Our team will confirm which forms and evidence are still needed.",
    },
    "documents_pending": {
        "summary": "We are waiting on some documents from you before we can file.",
        "next": "Please send the outstanding items listed below as soon as you can.",
    },
    "under_review": {
        "summary": "Your file is complete on our end and is being reviewed by our team before filing.",
        "next": "No action is needed from you right now.",
    },
    "filed": {
        "summary": "Your case has been filed with the relevant agency.",
        "next": "We are waiting for the agency's receipt notice and will update you as soon as it arrives.",
    },
    "rfe_received": {
        "summary": "The agency has requested additional evidence (an RFE) before they can decide your case.",
        "next": "We need the additional documents listed below to respond by the agency's deadline.",
    },
    "awaiting_decision": {
        "summary": "Your case has been fully submitted and is awaiting a decision from the agency.",
        "next": "No action is needed from you right now; processing times vary by case type.",
    },
    "approved": {
        "summary": "Good news -- your case has been approved.",
        "next": "We will send you the approval notice and any next steps by mail and email.",
    },
    "closed": {
        "summary": "This case is now closed.",
        "next": "Please contact our office if you have any questions about the outcome.",
    },
}


@dataclass
class RequiredDocument:
    name: str
    form_type: str  # exact form/format required, e.g. "notarized letter", "IRS Form W-2"
    received: bool = False
    due_date: Optional[date] = None


def case_from_db_record(record) -> "Case":
    """Build a Case (and its live outstanding-document list) from a
    db.CaseRecord ORM row. Keeps db.py free of domain/prompt logic and
    keeps this module free of any SQLAlchemy import."""
    return Case(
        case_id=record.case_id,
        client_name=record.client_name,
        case_type=record.case_type,
        stage=record.stage,
        language=record.client_language,
        required_documents=[
            RequiredDocument(
                name=d.name,
                form_type=d.form_type,
                received=d.received,
                due_date=d.due_date,
            )
            for d in record.documents
        ],
    )


@dataclass
class Case:
    case_id: str
    client_name: str
    case_type: str
    stage: str
    language: str = "en"
    required_documents: list[RequiredDocument] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.stage not in STAGE_LANGUAGE:
            raise ValueError(
                f"Unknown stage {self.stage!r}. Known stages: {sorted(STAGE_LANGUAGE)}. "
                "Add it to STAGE_LANGUAGE (a data change) before using it."
            )

    @property
    def stage_summary(self) -> str:
        return STAGE_LANGUAGE[self.stage]["summary"]

    @property
    def stage_next_step(self) -> str:
        return STAGE_LANGUAGE[self.stage]["next"]

    def outstanding_documents(self) -> list[RequiredDocument]:
        """The checklist is regenerated from the actual case file every
        time -- never a stale, previously-sent list."""
        return [d for d in self.required_documents if not d.received]

    def is_fully_documented(self) -> bool:
        return len(self.outstanding_documents()) == 0


# --- Prompt construction -----------------------------------------------------
#
# This is the ONLY place case data touches natural language sent to the
# AI. The stage summary/next-step text comes verbatim from STAGE_LANGUAGE
# above (never AI-authored), and only the outstanding-document checklist
# and light formatting are left to SuperDocs' drafting -- keeping the
# "approved language set" boundary enforceable and testable.

def build_letter_instruction(case: Case) -> str:
    outstanding = case.outstanding_documents()
    if outstanding:
        doc_lines = "\n".join(
            f"- {d.name} ({d.form_type})" + (f" -- due {d.due_date.isoformat()}" if d.due_date else "")
            for d in outstanding
        )
        checklist_block = f"Outstanding documents:\n{doc_lines}"
    else:
        checklist_block = "Outstanding documents: none -- your file is complete on our end."

    return (
        f"Draft a short, warm client update letter for {case.client_name} "
        f"regarding their {case.case_type} case (reference {case.case_id}).\n\n"
        f"Use exactly this status summary, do not add legal advice or predictions "
        f"beyond it: \"{case.stage_summary}\"\n\n"
        f"Use exactly this next-step language: \"{case.stage_next_step}\"\n\n"
        f"Then include this outstanding-documents checklist as a bulleted list, "
        f"verbatim, do not invent or omit any items:\n{checklist_block}\n\n"
        f"Write the letter in {case.language} language. Sign off as 'Case Management Team'. "
        f"Do not offer legal opinions, predictions about outcomes, or any language "
        f"outside of what was given above."
    )
