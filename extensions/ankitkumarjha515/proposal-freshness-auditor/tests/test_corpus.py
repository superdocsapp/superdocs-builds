"""Tests for freshness_auditor.corpus.

Loads the real fixture corpus and asserts its shape, then drives every
named validation error with a small inline YAML fixture per case.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from freshness_auditor.corpus import (
    Corpus,
    Document,
    DocumentNotFoundError,
    DuplicateDocumentIdError,
    InvalidDocumentRoleError,
    MissingDocumentFileError,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
CORPUS_PATH = FIXTURES_DIR / "corpus.yaml"


def write_corpus(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "corpus.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# --- real fixture corpus -------------------------------------------------


def test_loads_five_documents():
    corpus = Corpus.load(CORPUS_PATH)
    docs = corpus.documents()
    assert len(docs) == 5
    ids = {d.id for d in docs}
    assert ids == {
        "cap-statement",
        "annual-report-summary",
        "certifications-overview",
        "draft-proposal-alpha",
        "draft-proposal-beta",
    }


def test_by_role_splits_library_and_draft():
    corpus = Corpus.load(CORPUS_PATH)
    library = corpus.by_role("library")
    drafts = corpus.by_role("draft")
    assert len(library) == 3
    assert len(drafts) == 2
    assert {d.id for d in library} == {"cap-statement", "annual-report-summary", "certifications-overview"}
    assert {d.id for d in drafts} == {"draft-proposal-alpha", "draft-proposal-beta"}


def test_get_returns_document_with_resolved_path():
    corpus = Corpus.load(CORPUS_PATH)
    doc = corpus.get("cap-statement")
    assert isinstance(doc, Document)
    assert doc.role == "library"
    assert doc.title == "Northwind Relief Alliance — Capability Statement"
    assert doc.path.is_file()


def test_get_unknown_document_raises_named_error():
    corpus = Corpus.load(CORPUS_PATH)
    with pytest.raises(DocumentNotFoundError):
        corpus.get("does-not-exist")


def test_read_text_returns_raw_file_contents():
    corpus = Corpus.load(CORPUS_PATH)
    text = corpus.read_text("cap-statement")
    assert "Northwind Relief Alliance" in text
    assert "1,450 permanent staff" in text


def test_staffing_table_present_in_at_least_one_library_document():
    corpus = Corpus.load(CORPUS_PATH)
    library_texts = [corpus.read_text(d.id) for d in corpus.by_role("library")]
    assert any("<table>" in text and "Headcount" in text for text in library_texts)


# --- validation errors -------------------------------------------------


def test_duplicate_document_id_raises(tmp_path):
    (tmp_path / "a.html").write_text("<p>a</p>", encoding="utf-8")
    path = write_corpus(
        tmp_path,
        """
documents:
  - id: doc-1
    role: library
    path: a.html
    title: A
  - id: doc-1
    role: draft
    path: a.html
    title: A again
""",
    )
    with pytest.raises(DuplicateDocumentIdError):
        Corpus.load(path)


def test_unknown_role_raises(tmp_path):
    (tmp_path / "a.html").write_text("<p>a</p>", encoding="utf-8")
    path = write_corpus(
        tmp_path,
        """
documents:
  - id: doc-1
    role: not_a_real_role
    path: a.html
    title: A
""",
    )
    with pytest.raises(InvalidDocumentRoleError):
        Corpus.load(path)


def test_missing_file_raises(tmp_path):
    path = write_corpus(
        tmp_path,
        """
documents:
  - id: doc-1
    role: library
    path: does-not-exist.html
    title: A
""",
    )
    with pytest.raises(MissingDocumentFileError):
        Corpus.load(path)
