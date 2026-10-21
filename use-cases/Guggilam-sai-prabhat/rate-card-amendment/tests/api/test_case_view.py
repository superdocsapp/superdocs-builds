"""Tests for app/backend/case_view.py's amendment-letter rendering, in
particular that raw Markdown heading markup from PricingClause.clause_reference
never leaks into the rendered letter, and a missing rate_schedule_reference
gets a readable fallback instead of the literal string 'None'.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.backend.case_view import render_amendment_letter
from src.amendment_case import build_case


@pytest.fixture
def rate_entries(repo_root):
    from src.extraction.rate_tables import extract_rate_entries
    from src.extraction.text_extraction import extract_document_text

    old_path = repo_root / "fixtures/rate-cards/rate_card_old_2024Q1.csv"
    new_path = repo_root / "fixtures/rate-cards/rate_card_new_2025Q3.csv"
    old_entries = extract_rate_entries(str(old_path), extract_document_text(str(old_path)))
    new_entries = extract_rate_entries(str(new_path), extract_document_text(str(new_path)))
    return old_entries, new_entries


def test_rendered_letter_has_no_raw_markdown_heading_markup(repo_root, rate_entries, reference_date):
    old_entries, new_entries = rate_entries
    contract_path = str(repo_root / "fixtures/contracts/contract_01_northstar.md")
    case = build_case(
        case_id="case_01",
        contract_path=contract_path,
        old_rate_entries=old_entries,
        new_rate_entries=new_entries,
        reference_date=reference_date,
        proposed_effective_date=date(2025, 9, 15),
    )

    letter = render_amendment_letter(case)
    assert "## Article" not in letter
    assert "None" not in letter
