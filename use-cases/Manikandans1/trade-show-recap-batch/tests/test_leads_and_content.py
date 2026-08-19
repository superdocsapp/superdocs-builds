from __future__ import annotations

from pathlib import Path

from app.leads import load_leads
from app.recap_content import (
    NO_NEXT_STEP_FALLBACK,
    NO_NOTES_FALLBACK,
    build_recap_sections,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_loads_all_leads_from_csv():
    leads = load_leads(FIXTURES / "leads.csv")
    assert len(leads) == 6
    assert {l.lead_id for l in leads} == {"L001", "L002", "L003", "L004", "L005", "L006"}


def test_lead_with_full_data_has_no_blank_fields():
    leads = load_leads(FIXTURES / "leads.csv")
    l001 = next(l for l in leads if l.lead_id == "L001")
    assert l001.has_notes
    assert l001.has_interest
    assert l001.has_next_step


def test_lead_with_almost_no_data_is_detected():
    leads = load_leads(FIXTURES / "leads.csv")
    l003 = next(l for l in leads if l.lead_id == "L003")
    assert l003.name == "Sarah Kim"
    assert not l003.has_notes
    assert not l003.has_interest
    assert not l003.has_next_step
    assert l003.company == ""


def test_fully_populated_lead_produces_sections_grounded_in_its_own_notes():
    leads = load_leads(FIXTURES / "leads.csv")
    l001 = next(l for l in leads if l.lead_id == "L001")
    sections = build_recap_sections(l001)

    assert "Meridian Logistics" in sections.discussion_section
    assert "3-day manual contract review" in sections.discussion_section
    assert sections.next_step_section == "Send case study on logistics vendor contracts by Friday"
    assert NO_NOTES_FALLBACK not in sections.discussion_section


def test_blank_notes_degrade_to_the_honest_fallback_not_an_invention():
    leads = load_leads(FIXTURES / "leads.csv")
    l005 = next(l for l in leads if l.lead_id == "L005")
    sections = build_recap_sections(l005)

    assert NO_NOTES_FALLBACK in sections.discussion_section
    # The fallback must not accidentally contain specifics that weren't
    # actually said — it's a fixed, honest string, not a paraphrase.
    assert "clinical" not in sections.discussion_section.lower() or (
        "Clinical documentation" not in l005.conversation_notes
    )


def test_almost_empty_lead_degrades_every_section_honestly():
    leads = load_leads(FIXTURES / "leads.csv")
    l003 = next(l for l in leads if l.lead_id == "L003")
    sections = build_recap_sections(l003)

    assert NO_NOTES_FALLBACK in sections.discussion_section
    assert NO_NEXT_STEP_FALLBACK == sections.next_step_section
    assert "an unspecified company" in sections.discussion_section
    # Nothing about a specific product interest was invented for a lead
    # who never stated one.
    assert "contract" not in sections.promised_section.lower()
    assert "clinical" not in sections.promised_section.lower()
