import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import docx


def make_test_docx(path: str, paragraphs: list[str]):
    doc = docx.Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(path)


def check_text_state(
    docx_path: str, expect_texts=None, forbid_texts=None, forbid_duplicates=None
):
    """Standalone re-implementation of the core logic in verify_export_state,
    extracted so it can be tested against synthetic files without needing a
    live SuperDocs export — the real function's logic is exercised
    end-to-end throughout PROGRESS.md's investigations; this covers the
    decision logic itself in isolation."""
    doc = docx.Document(docx_path)
    text = "\n".join(p.text for p in doc.paragraphs)

    if expect_texts:
        missing = [t for t in expect_texts if t not in text]
        if missing:
            return False, f"missing: {missing}"
    if forbid_texts:
        present = [t for t in forbid_texts if t in text]
        if present:
            return False, f"forbidden present: {present}"
    if forbid_duplicates:
        duplicated = [t for t in forbid_duplicates if text.count(t) > 1]
        if duplicated:
            return False, f"duplicated: {duplicated}"
    return True, "ok"


def test_detects_missing_expected_content(tmp_path):
    path = str(tmp_path / "test.docx")
    make_test_docx(path, ["Some content", "But not the real data"])

    ok, reason = check_text_state(path, expect_texts=["Alvarez 2021"])
    assert ok is False
    assert "missing" in reason


def test_detects_fabricated_placeholder_content(tmp_path):
    path = str(tmp_path / "test.docx")
    make_test_docx(path, ["Study ID", "Please fill: Author (Year)"])

    ok, reason = check_text_state(path, forbid_texts=["Please fill"])
    assert ok is False
    assert "forbidden" in reason


def test_detects_duplicated_heading(tmp_path):
    path = str(tmp_path / "test.docx")
    make_test_docx(
        path,
        [
            "Risk of Bias Summary",
            "some content",
            "Risk of Bias Summary",
            "more content",
        ],
    )

    ok, reason = check_text_state(path, forbid_duplicates=["Risk of Bias Summary"])
    assert ok is False
    assert "duplicated" in reason


def test_passes_when_content_is_correct_and_unique(tmp_path):
    path = str(tmp_path / "test.docx")
    make_test_docx(path, ["Alvarez 2021", "Risk of Bias Summary", "real data only"])

    ok, reason = check_text_state(
        path,
        expect_texts=["Alvarez 2021"],
        forbid_texts=["Please fill"],
        forbid_duplicates=["Risk of Bias Summary"],
    )
    assert ok is True
