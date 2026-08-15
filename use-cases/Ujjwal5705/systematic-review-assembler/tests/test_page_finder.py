import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import fitz
from page_finder import find_page_for_text, build_checklist_page_map


def make_test_pdf(path: str, pages_text: list[str]):
    """Builds a minimal real PDF with known text on known pages, so page
    detection can be tested without hitting the SuperDocs API."""
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_find_page_for_text_locates_correct_page(tmp_path):
    pdf_path = str(tmp_path / "test.pdf")
    make_test_pdf(
        pdf_path,
        ["Introduction section here", "Methods section here", "Results section here"],
    )

    assert find_page_for_text(pdf_path, "Methods section") == 2
    assert find_page_for_text(pdf_path, "Results section") == 3
    assert find_page_for_text(pdf_path, "Introduction") == 1


def test_find_page_for_text_returns_none_when_absent(tmp_path):
    pdf_path = str(tmp_path / "test.pdf")
    make_test_pdf(pdf_path, ["Only this page exists"])

    assert find_page_for_text(pdf_path, "Nonexistent content") is None


def test_find_page_for_text_returns_first_occurrence(tmp_path):
    pdf_path = str(tmp_path / "test.pdf")
    make_test_pdf(pdf_path, ["Duplicate phrase here", "Duplicate phrase here again"])

    # Should return the FIRST page it appears on, not the last
    assert find_page_for_text(pdf_path, "Duplicate phrase") == 1


def test_build_checklist_page_map_handles_mixed_found_and_missing(tmp_path):
    pdf_path = str(tmp_path / "test.pdf")
    make_test_pdf(pdf_path, ["Title of the document", "Some other content"])

    items = [
        {"item": "Title", "description": "d1", "anchor_text": "Title of the document"},
        {
            "item": "Missing Item",
            "description": "d2",
            "anchor_text": "text that does not exist anywhere",
        },
    ]
    result = build_checklist_page_map(pdf_path, items)

    assert result[0]["page"] == 1
    assert result[1]["page"] is None
