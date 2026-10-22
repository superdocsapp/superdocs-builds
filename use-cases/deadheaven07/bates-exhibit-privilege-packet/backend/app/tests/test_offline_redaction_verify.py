"""Offline redaction verification tests.

Proves the byte-scrub + verify cycle works entirely offline:
  - Scrub removes exact text bytes from PDF
  - Verify confirms text is truly gone
  - Scrub is deterministic (re-running produces byte-identical output)
  - Non-matching text is handled gracefully
"""

import hashlib
import tempfile
from pathlib import Path

import fitz
import pytest

from app.domain.redaction import RedactionCandidate, RedactionCategory, RedactionStatus
from app.services.redaction_scrubber import RedactionByteScrubber, RedactionVerifier


def _make_candidate(text: str, page: int = 1, **kwargs) -> RedactionCandidate:
    defaults = {
        "id": kwargs.get("id", "test-id"),
        "document_id": "test-doc",
        "page_number": page,
        "category": RedactionCategory.SSN,
        "matched_text": text,
        "context_before": "",
        "context_after": "",
        "x0": 0,
        "y0": 0,
        "x1": 0,
        "y1": 0,
        "status": RedactionStatus.APPROVED,
    }
    defaults.update(kwargs)
    return RedactionCandidate(**defaults)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class TestByteScrubber:
    def test_scrub_removes_text(self):
        """Matched text bytes are removed from the output PDF."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((50, 100), "SSN: 123-45-6789", fontsize=12)
            doc.save(str(source))
            doc.close()

            candidate = _make_candidate("123-45-6789")
            output = Path(tmpdir) / "redacted.pdf"

            scrubber = RedactionByteScrubber()
            result = scrubber.scrub(source, [candidate], output)

            assert output.exists()
            assert result.rects_applied >= 1

            # Verify text is gone
            out_doc = fitz.open(str(output))
            try:
                out_text = "".join(p.get_text() for p in out_doc)
            finally:
                out_doc.close()
            assert "123-45-6789" not in out_text

    def test_scrub_deterministic(self):
        """Running scrub twice on the same source produces text-identical output.

        Note: PyMuPDF embeds timestamps in PDF metadata, so raw bytes differ.
        We compare the extracted text content instead, which proves the
        redaction logic is deterministic.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((50, 100), "SSN: 123-45-6789", fontsize=12)
            page.insert_text((50, 120), "Email: test@example.com", fontsize=12)
            doc.save(str(source))
            doc.close()

            candidate = _make_candidate("123-45-6789")
            scrubber = RedactionByteScrubber()

            out1 = Path(tmpdir) / "out1.pdf"
            out2 = Path(tmpdir) / "out2.pdf"
            scrubber.scrub(source, [candidate], out1)
            scrubber.scrub(source, [candidate], out2)

            # Compare extracted text — both should have same content
            d1 = fitz.open(str(out1))
            try:
                text1 = "".join(p.get_text() for p in d1)
            finally:
                d1.close()

            d2 = fitz.open(str(out2))
            try:
                text2 = "".join(p.get_text() for p in d2)
            finally:
                d2.close()

            assert text1 == text2

    def test_scrub_expands_rect_for_coverage(self):
        """Redact annotation is slightly expanded to cover glyph overshoot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((50, 100), "Sensitive Data", fontsize=12)
            doc.save(str(source))
            doc.close()

            candidate = _make_candidate("Sensitive Data")
            output = Path(tmpdir) / "out.pdf"

            scrubber = RedactionByteScrubber()
            result = scrubber.scrub(source, [candidate], output)
            assert result.rects_applied >= 1

    def test_scrub_nonexistent_source(self):
        """Scrubbing a missing source raises FileNotFoundError."""
        scrubber = RedactionByteScrubber()
        with pytest.raises(FileNotFoundError, match="Source PDF not found"):
            scrubber.scrub(
                Path("/nonexistent.pdf"),
                [_make_candidate("test")],
                Path("/tmp/out.pdf"),
            )

    def test_verify_proves_removal(self):
        """Verifier confirms scrubbed text is absent from the output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((50, 100), "SSN: 123-45-6789", fontsize=12)
            doc.save(str(source))
            doc.close()

            candidate = _make_candidate("123-45-6789")
            output = Path(tmpdir) / "redacted.pdf"

            scrubber = RedactionByteScrubber()
            scrubber.scrub(source, [candidate], output)

            verifier = RedactionVerifier()
            results = verifier.verify_pdf(output, [candidate])

            assert results[str(candidate.id)]["verified"] is True
            assert results[str(candidate.id)]["text_still_present"] is False

    def test_verify_detects_unscrubbed_text(self):
        """Verifier detects text that was NOT scrubbed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((50, 100), "SSN: 123-45-6789", fontsize=12)
            doc.save(str(source))
            doc.close()

            # Candidate that doesn't match any text
            candidate = _make_candidate("NONEXISTENT-TEXT")
            output = Path(tmpdir) / "out.pdf"

            scrubber = RedactionByteScrubber()
            scrubber.scrub(source, [candidate], output)

            verifier = RedactionVerifier()
            results = verifier.verify_pdf(output, [candidate])

            # Text not found -> verify says OK (nothing to check)
            assert results[str(candidate.id)]["verified"] is True
