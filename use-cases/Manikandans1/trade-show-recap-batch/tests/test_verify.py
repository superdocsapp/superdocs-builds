from __future__ import annotations

from app.leads import Lead
from app.recap_content import build_recap_sections
from app.verify import verify_recap_text


def _sections_for(**overrides):
    defaults = dict(
        lead_id="L999", name="Jane Doe", company="Acme Co",
        conversation_notes="Talked about pricing.", interest="Widgets", next_step="Send a demo",
    )
    defaults.update(overrides)
    lead = Lead(**defaults)
    return build_recap_sections(lead)


def test_well_formed_document_has_no_issues():
    sections = _sections_for()
    rendered = (
        f"Lead: {sections.lead_name}, {sections.lead_company}\n"
        f"WHAT WE DISCUSSED\n{sections.discussion_section}\n"
        f"WHAT WE PROMISED\n{sections.promised_section}\n"
        f"NEXT STEP\n{sections.next_step_section}\n"
    )
    assert verify_recap_text(rendered, sections) == []


def test_unresolved_placeholder_is_flagged():
    sections = _sections_for()
    rendered = "Lead: {{lead_name}}, {{lead_company}}\n(nothing substituted)"
    issues = verify_recap_text(rendered, sections)
    assert any("unresolved placeholder" in issue for issue in issues)


def test_missing_expected_value_is_flagged():
    sections = _sections_for()
    # Discussion section is simply missing from the "rendered" text.
    rendered = f"Lead: {sections.lead_name}, {sections.lead_company}\n"
    issues = verify_recap_text(rendered, sections)
    assert any("discussion_section" in issue for issue in issues)
