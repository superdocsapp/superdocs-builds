"""Tests for src/rate_diff.py using the real fixture rate cards."""

from __future__ import annotations

from src.extraction.rate_tables import extract_rate_entries
from src.extraction.text_extraction import extract_document_text
from src.rate_diff import diff_rate_cards


def test_diff_against_fixture_rate_cards(repo_root):
    old_path = repo_root / "fixtures/rate-cards/rate_card_old_2024Q1.csv"
    new_path = repo_root / "fixtures/rate-cards/rate_card_new_2025Q3.csv"

    old_entries = extract_rate_entries(str(old_path), extract_document_text(str(old_path)))
    new_entries = extract_rate_entries(str(new_path), extract_document_text(str(new_path)))

    changes = diff_rate_cards("contract_01", old_entries, new_entries)

    assert len(changes) == 10
    by_destination = {c.destination: c for c in changes}

    us = by_destination["United States"]
    assert us.old_rate_usd_per_min is not None
    assert us.new_rate_usd_per_min == 0.0039
    assert us.change_pct is not None
    assert us.change_pct < 0  # rate_card_new says -4.9% for US

    uk = by_destination["United Kingdom"]
    assert uk.change_pct is not None
    assert uk.change_pct > 0  # +5.2%


def test_diff_carries_citation_to_both_sides(repo_root):
    old_path = repo_root / "fixtures/rate-cards/rate_card_old_2024Q1.csv"
    new_path = repo_root / "fixtures/rate-cards/rate_card_new_2025Q3.csv"
    old_entries = extract_rate_entries(str(old_path), extract_document_text(str(old_path)))
    new_entries = extract_rate_entries(str(new_path), extract_document_text(str(new_path)))

    changes = diff_rate_cards("contract_01", old_entries, new_entries)
    for change in changes:
        assert change.citation.document_id == "contract_01"
        assert "new:" in change.citation.source_span
        assert 0.0 <= change.citation.confidence <= 1.0


def test_new_destination_with_no_old_entry_has_null_old_rate():
    from src.domain.models import ExtractionMethod, RateEntry, SourceCitation

    def entry(destination, rate):
        return RateEntry(
            rate_card_id="RC",
            destination=destination,
            prefix=None,
            rate_usd_per_min=rate,
            effective_date=None,
            expiry_date=None,
            citation=SourceCitation(
                document_id="rc",
                source_span=f"destination={destination}",
                confidence=1.0,
                extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
            ),
        )

    old_entries = [entry("United States", 0.004)]
    new_entries = [entry("United States", 0.0039), entry("Fiji", 0.05)]

    changes = diff_rate_cards("contract_x", old_entries, new_entries)
    by_destination = {c.destination: c for c in changes}

    fiji = by_destination["Fiji"]
    assert fiji.old_rate_usd_per_min is None
    assert fiji.change_pct is None
    assert fiji.citation.confidence == 0.5
