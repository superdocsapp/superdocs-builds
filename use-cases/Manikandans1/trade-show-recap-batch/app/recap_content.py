"""Builds the three narrative sections (discussion, promised, next step)
for one lead's recap document. This is deliberately plain Python string
assembly from the Lead record's own fields, not an LLM asked to
'summarize the conversation' — the 'no invented specifics' requirement
is enforced structurally here, before SuperDocs ever sees an instruction,
rather than relying on a model's judgment about what it should and
shouldn't make up.

Every value that appears in a built section either came from this exact
Lead instance, or is one of the two fixed, honest fallback strings below.
There is no path by which text from a different lead's record, or an
invented detail, can end up in these sections.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.leads import Lead

NO_NOTES_FALLBACK = (
    "No specific notes were recorded for this conversation at the booth."
)
NO_NEXT_STEP_FALLBACK = (
    "No specific next step was recorded — following up with a general "
    "check-in is recommended."
)


@dataclass(frozen=True)
class RecapSections:
    lead_id: str
    lead_name: str
    lead_company: str
    discussion_section: str
    promised_section: str
    next_step_section: str


def build_recap_sections(lead: Lead) -> RecapSections:
    company = lead.company or "an unspecified company"

    if lead.has_notes:
        discussion = (
            f"{lead.name} from {company} stopped by the booth. "
            f"{lead.conversation_notes}"
        )
    else:
        discussion = f"{lead.name} from {company}. {NO_NOTES_FALLBACK}"

    if lead.has_interest:
        promised = (
            f"Based on their stated interest in {lead.interest.lower()}, "
            f"the team noted this as a follow-up area."
        )
    else:
        promised = (
            "No specific area of interest was recorded, so no particular "
            "commitment was made beyond general follow-up."
        )

    if lead.has_next_step:
        next_step = lead.next_step
    else:
        next_step = NO_NEXT_STEP_FALLBACK

    return RecapSections(
        lead_id=lead.lead_id,
        lead_name=lead.name,
        lead_company=company,
        discussion_section=discussion,
        promised_section=promised,
        next_step_section=next_step,
    )
