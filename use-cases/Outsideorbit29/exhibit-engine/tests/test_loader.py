"""Text extraction from the mixed-format evidence pile."""

from __future__ import annotations

import html
from pathlib import Path

import pytest

from exhibit.loader import extract_text, load_evidence, SUPPORTED

SAMPLE = Path(__file__).resolve().parent.parent / "sample" / "evidence"


def test_extract_txt():
    text = extract_text(SAMPLE / "joint_lease.txt")
    assert "JOINT LEASE" in text
    assert "Austin" in text


def test_extract_markdown():
    text = extract_text(SAMPLE / "travel_itinerary.md")
    assert "Travel Itinerary" in text
    assert "2024" in text


def test_extract_docx():
    text = extract_text(SAMPLE / "marriage_certificate.docx")
    assert "MARRIAGE CERTIFICATE" in text


def test_extract_pdf():
    text = extract_text(SAMPLE / "passport.pdf")
    assert "PASSPORT" in text or "PASSORT" in text
    assert "S4827371" in text


def test_extract_plain_html():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "note.html"
        p.write_text(html.escape("<p>Evidence in a web page.</p>"), encoding="utf-8")
        text = extract_text(p)
        assert "Evidence in a web page." in text


def test_unsupported_extension_raises():
    with pytest.raises(ValueError):
        extract_text("scan.tar.gz")


def test_load_evidence_collects_all():
    items = load_evidence([str(p) for p in sorted(SAMPLE.iterdir())])
    assert len(items) == len(list(SAMPLE.iterdir()))
    assert all(item.text for item in items)
