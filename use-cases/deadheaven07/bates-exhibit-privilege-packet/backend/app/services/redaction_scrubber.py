"""True byte-scrubbing via PyMuPDF (APPLIED AFTER HUMAN APPROVAL).

Pipeline position:
  SuperDocs proposes (ask_every_time) -> human approves -> THIS MODULE removes
  the bytes -> redacted artifact is re-imported into SuperDocs -> final packet
  is exported as a native SuperDocs document.

This module is DB-free so the scrub + verify cycle can be proven entirely
offline.  It is NOT the primary intelligence layer — it is the deterministic
post-approval processing step that removes matched text bytes from the PDF
content stream using PyMuPDF redact annotations.

Fallback path note: when running in local fallback mode (no SuperDocs API key),
this module still performs the byte-scrub, but the re-import step is skipped
and the local artifact is the final deliverable.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from app.domain.redaction import RedactionCandidate

logger = logging.getLogger(__name__)


@dataclass
class ScrubResult:
    output_path: Path
    rects_applied: int = 0
    texts_not_found: list[str] = field(default_factory=list)
    pages_processed: int = 0


class RedactionByteScrubber:
    """Removes matched text bytes from a PDF using PyMuPDF redact annotations.

    Always scrubs from the pristine base so re-application is deterministic
    (re-running with the same candidate set produces byte-identical output).

    Fallback for scanned/image PDFs: when ``page.search_for()`` returns no
    results (text is part of an embedded image), the candidate's explicit
    ``x0/y0/x1/y1`` coordinates from detection are used to create a redaction
    annot that permanently covers the pixel area.
    """

    def scrub(
        self,
        source: Path,
        candidates: list[RedactionCandidate],
        output: Path,
    ) -> ScrubResult:
        if not source.exists():
            raise FileNotFoundError(f"Source PDF not found: {source}")
        if not candidates:
            raise ValueError("No candidates to scrub")

        doc = fitz.open(source)
        try:
            result = ScrubResult(output_path=output)
            matched_ids: set[str] = set()
            for candidate in candidates:
                if not candidate.matched_text:
                    continue
                page_index = (candidate.page_number or 1) - 1
                if page_index < 0 or page_index >= len(doc):
                    result.texts_not_found.append(
                        f"{candidate.matched_text} (page {candidate.page_number} out of range)"
                    )
                    continue

                # Try search_for first (selectable text PDFs)
                page = doc[page_index]
                rects = page.search_for(candidate.matched_text)

                if not rects:
                    # Fallback for scanned/image PDFs: use the candidate's
                    # explicit coordinates from detection. The candidate's
                    # x0/y0/x1/y1 are in PDF page coordinate space.
                    if (
                        candidate.x0 is not None
                        and candidate.y0 is not None
                        and candidate.x1 is not None
                        and candidate.y1 is not None
                    ):
                        rect = fitz.Rect(
                            float(candidate.x0),
                            float(candidate.y0),
                            float(candidate.x1),
                            float(candidate.y1),
                        )
                        # Expand slightly so glyphs are fully covered
                        rect = rect + fitz.Rect(-2, -2, 2, 2)
                        page.add_redact_annot(rect, fill=(0, 0, 0))
                        result.rects_applied += 1
                        matched_ids.add(candidate.matched_text)
                    else:
                        result.texts_not_found.append(candidate.matched_text)
                    continue

                for rect in rects:
                    page.add_redact_annot(rect, fill=(0, 0, 0))
                    result.rects_applied += 1
                matched_ids.add(candidate.matched_text)

            for page in doc:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            output.parent.mkdir(parents=True, exist_ok=True)
            doc.save(output, garbage=4, deflate=True)
            result.pages_processed = len(doc)
            return result
        finally:
            doc.close()


class RedactionVerifier:
    """Scans a scrubbed PDF to prove the approved text bytes are gone.

    The packet build gate refuses to build if any APPLIED redaction's text
    is still extractable from the redacted artifact.
    """

    def verify_pdf(
        self,
        redacted_path: Path,
        candidates: list[RedactionCandidate],
    ) -> dict[str, dict]:
        if not redacted_path.exists():
            return {
                str(c.id): {
                    "verified": False,
                    "text_still_present": True,
                    "error": "redacted file missing",
                }
                for c in candidates
            }

        doc = fitz.open(redacted_path)
        try:
            pages = [page.get_text() for page in doc]
        finally:
            doc.close()

        results: dict[str, dict] = {}
        for candidate in candidates:
            page_index = (candidate.page_number or 1) - 1
            text = candidate.matched_text or ""
            if not text:
                results[str(candidate.id)] = {"verified": True, "text_still_present": False}
                continue
            page_text = pages[page_index] if 0 <= page_index < len(pages) else "\n".join(pages)
            still_present = text.lower() in page_text.lower()
            results[str(candidate.id)] = {
                "verified": not still_present,
                "text_still_present": still_present,
            }
        return results
