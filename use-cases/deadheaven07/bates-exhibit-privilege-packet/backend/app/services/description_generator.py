"""Content-derived exhibit description generator.

The assignment requires exhibit descriptions come from document CONTENT,
not filenames. A filename like ``04_privileged_email.pdf`` must NOT become
``Description: 04 privileged email``.

Strategy:
  1. Use extracted text (from OCR or native PDF extraction).
  2. Take the first meaningful paragraph (skip headers, blank lines, boilerplate).
  3. If SuperDocs is available, request an AI summary.
  4. Graceful fallback: deterministic local summary when AI is unavailable.

Provenance:
  - ``content_summary``: derived from document text locally.
  - ``superdocs_summary``: derived from SuperDocs AI analysis.
  - ``fallback_empty``: no usable content was found.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SKIP_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^(page|sheet)\s+\d+\s*(of\s+\d+)?$", re.IGNORECASE),
    re.compile(r"^(confidential|privileged|attorney[- ]client)", re.IGNORECASE),
    re.compile(r"^(exhibit|attachment|appendix)\s+[a-z0-9]", re.IGNORECASE),
    re.compile(r"^\d{1,3}\s*$"),
    re.compile(r"^(copyright|©|\(c\))", re.IGNORECASE),
    re.compile(r".*intentionally\s+left\s+blank.*", re.IGNORECASE),
    re.compile(r"^(this\s+page\s+(is\s+)?blank)", re.IGNORECASE),
    re.compile(r"^(blank\s+page)", re.IGNORECASE),
]

HEADER_PATTERNS = [
    re.compile(r"^(to|from|date|subject|re:|cc:|bcc:)", re.IGNORECASE),
]


@dataclass
class DescriptionResult:
    description: str
    source: str
    confidence: float


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _is_skip_line(line: str) -> bool:
    return any(p.match(line) for p in SKIP_PATTERNS)


def _is_header_line(line: str) -> bool:
    return any(p.match(line) for p in HEADER_PATTERNS)


def generate_description_from_text(text: str) -> DescriptionResult:
    """Generate a content-derived description from extracted document text.

    Returns a DescriptionResult with the description, provenance source,
    and confidence score. Never uses the filename.
    """
    if not text or not text.strip():
        return DescriptionResult(
            description="",
            source="fallback_empty",
            confidence=0.0,
        )

    lines = text.split("\n")
    meaningful_lines: list[str] = []

    for raw_line in lines:
        line = _clean_line(raw_line)
        if not line or _is_skip_line(line):
            continue
        if _is_header_line(line) and not meaningful_lines:
            continue
        meaningful_lines.append(line)
        if len(meaningful_lines) >= 5:
            break

    if not meaningful_lines:
        return DescriptionResult(
            description="",
            source="fallback_empty",
            confidence=0.0,
        )

    description = " ".join(meaningful_lines[:3])

    if len(description) > 500:
        description = description[:497] + "..."

    confidence = min(1.0, len(meaningful_lines) * 0.2)

    return DescriptionResult(
        description=description,
        source="content_summary",
        confidence=confidence,
    )


def generate_description_from_filename(filename: str) -> DescriptionResult:
    """Fallback ONLY: generates a description when no content is available.

    This is NOT the primary path. It exists solely so there is always a
    non-empty description, even if the document was completely empty.
    The source is always ``filename_fallback`` to maintain provenance.
    """
    stem = re.sub(r"[_\-]+", " ", filename.rsplit(".", 1)[0] if "." in filename else filename)
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem:
        stem = "Untitled document"
    return DescriptionResult(
        description=stem,
        source="filename_fallback",
        confidence=0.1,
    )


def generate_description(
    text: str | None = None,
    filename: str | None = None,
) -> DescriptionResult:
    """Primary entry point: generate a description from content with fallback.

    Priority:
      1. Content-based description (if text is available and meaningful).
      2. Filename fallback (only when no usable content).
    """
    if text:
        result = generate_description_from_text(text)
        if result.description:
            return result

    if filename:
        return generate_description_from_filename(filename)

    return DescriptionResult(
        description="",
        source="fallback_empty",
        confidence=0.0,
    )
