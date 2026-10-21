"""Steps 1-2 and 4-5: document classification, text extraction, rate tables.

Runs without a live model key: classification and CSV parsing are pure
deterministic rules over fixture files on disk.
"""

from __future__ import annotations

from src.domain.models import DocumentType
from src.extraction.classification import classify_document
from src.extraction.rate_tables import extract_old_rates, extract_rate_entries
from src.extraction.text_extraction import extract_document_text


def test_classify_contracts(repo_root):
    for name in [
        "contract_01_northstar.md",
        "contract_02_bluewire.md",
        "contract_03_summitlink.md",
        "contract_04_ironvale.md",
        "contract_05_pelagic.md",
    ]:
        path = repo_root / "fixtures" / "contracts" / name
        text = extract_document_text(str(path))
        assert classify_document(str(path), text) == DocumentType.CONTRACT


def test_classify_rate_cards(repo_root):
    for name in ["rate_card_old_2024Q1.csv", "rate_card_new_2025Q3.csv"]:
        path = repo_root / "fixtures" / "rate-cards" / name
        text = extract_document_text(str(path))
        assert classify_document(str(path), text) == DocumentType.RATE_CARD


def test_classify_playbook_and_template(repo_root):
    playbook_path = repo_root / "fixtures" / "playbooks" / "contract_review_playbook.md"
    template_path = repo_root / "fixtures" / "templates" / "amendment_letter_template.md"

    assert (
        classify_document(str(playbook_path), extract_document_text(str(playbook_path)))
        == DocumentType.PLAYBOOK
    )
    assert (
        classify_document(str(template_path), extract_document_text(str(template_path)))
        == DocumentType.AMENDMENT_LETTER_TEMPLATE
    )


def test_old_rate_card_extraction(repo_root, expected_results):
    path = repo_root / expected_results["rate_cards"]["old"]["file"]
    text = extract_document_text(str(path))
    entries = extract_rate_entries(str(path), text)
    old_entries = extract_old_rates(str(path), text)

    expected = expected_results["rate_cards"]["old"]
    assert len(entries) == expected["row_count"]
    assert len(old_entries) == expected["row_count"]
    assert all(entry.rate_card_id == expected["rate_card_id"] for entry in entries)
    assert all(entry.effective_date == expected["effective_date"] for entry in entries)


def test_new_rate_card_has_no_expiry_and_is_not_old(repo_root, expected_results):
    path = repo_root / expected_results["rate_cards"]["new"]["file"]
    text = extract_document_text(str(path))
    entries = extract_rate_entries(str(path), text)
    old_entries = extract_old_rates(str(path), text)

    expected = expected_results["rate_cards"]["new"]
    assert len(entries) == expected["row_count"]
    assert len(old_entries) == 0
    assert all(entry.rate_card_id == expected["rate_card_id"] for entry in entries)


def test_every_rate_entry_is_cited(repo_root, expected_results):
    path = repo_root / expected_results["rate_cards"]["old"]["file"]
    text = extract_document_text(str(path))
    for entry in extract_rate_entries(str(path), text):
        assert entry.citation.document_id
        assert entry.citation.source_span
        assert entry.citation.confidence == 1.0
