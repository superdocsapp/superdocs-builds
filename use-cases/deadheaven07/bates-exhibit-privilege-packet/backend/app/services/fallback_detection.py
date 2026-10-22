"""Local fallback intelligence path (DEMOTED).

This module is the historical local-heavy detection engine (PyMuPDF text
extraction + regex + OCR-derived text). Since the SuperDocs-as-substrate
refactor it is **strictly a fallback**: it is only invoked when the primary
SuperDocs intelligence layer is unavailable (no real API key, network failure,
or upstream error), and every proposal it produces is explicitly labeled with
``proposed_by="local_fallback"`` so provenance is never ambiguous.

It exists so the compliance workflow (Bates continuity, redaction verification,
packet build) remains fully operational offline and its behaviour is pinned by
the offline unit suite (H-1 account patterns, privilege-marker false-positive
guards, per-occurrence and cross-line behavior).
"""

import logging
import re
from dataclasses import dataclass

import fitz

from app.domain.redaction import RedactionCategory

logger = logging.getLogger(__name__)

PROVENANCE_LOCAL_FALLBACK = "local_fallback"

# ---------------------------------------------------------------------- #
# Patterns. Intentionally conservative: Bates labels, invoice numbers,
# docket numbers and calendar dates must never be flagged.
# ---------------------------------------------------------------------- #
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
# Alphanumeric accounts: ACC-8821-4433, ACC 8821 4433, ACCOUNT-8821-4433.
ALNUM_ACCOUNT_RE = re.compile(r"\b(?:ACC|ACCT|ACCOUNT)[\s-]?\d{4}[\s-]\d{4}\b", re.IGNORECASE)
# Pure numeric accounts: 8821-4433-2211-9900.
NUMERIC_ACCOUNT_RE = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b")

MEDICAL_TERMS = [
    "diagnosis",
    "prescription",
    "medication",
    "treatment",
    "psychiatric",
    "hiv",
    "cancer",
]

TWO_WORD_NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}\s[A-Z][a-z]{2,}\b")

# Words that must never participate in a NAME proposal. Privilege markers and
# document scaffolding words are the primary false-positive source.
NAME_STOPLIST = {
    "attorney",
    "client",
    "privileged",
    "privilege",
    "communication",
    "confidential",
    "legal",
    "advice",
    "counsel",
    "account",
    "record",
    "invoice",
    "statement",
    "reference",
    "page",
    "date",
    "term",
    "parties",
    "employee",
    "contract",
    "business",
    "email",
    "attached",
    "prepared",
    "reviewed",
    "approved",
    "summary",
    "service",
    "settlement",
    "strategy",
    "monthly",
    "activity",
    "contained",
    "memo",
    "regarding",
    "negotiation",
    "position",
    "renewal",
    "revised",
    "alternate",
    "number",
    "phone",
    "name",
    "bank",
    "routing",
    "customer",
    "policy",
    "address",
    "street",
    "avenue",
    "road",
    "suite",
    "city",
    "state",
    "zip",
    "patient",
    "diagnosis",
    "prescription",
    "medication",
    "treatment",
}


@dataclass
class RedactionMatch:
    category: RedactionCategory
    matched_text: str
    context_before: str
    context_after: str
    page_number: int
    x0: float
    y0: float
    x1: float
    y1: float


def _word_rects_from_line(
    line_text: str, words: list[tuple[str, tuple[float, float, float, float]]]
) -> list[tuple[int, int, tuple[float, float, float, float]]]:
    """Map (start, end) char offsets in the joined line text to word rects."""
    mapping = []
    offset = 0
    for word, rect in words:
        start = line_text.find(word, offset)
        if start == -1:
            continue
        mapping.append((start, start + len(word), rect))
        offset = start + len(word)
    return mapping


def _match_rect(
    span_start: int,
    span_end: int,
    mapping: list[tuple[int, int, tuple[float, float, float, float]]],
) -> tuple[float, float, float, float] | None:
    overlapping = [
        (max(span_start, s), min(span_end, e), rect)
        for s, e, rect in mapping
        if s < span_end and e > span_start
    ]
    if not overlapping:
        return None
    x0 = min(rect[0] for _, _, rect in overlapping)
    y0 = min(rect[1] for _, _, rect in overlapping)
    x1 = max(rect[2] for _, _, rect in overlapping)
    y1 = max(rect[3] for _, _, rect in overlapping)
    return x0, y0, x1, y1


def _detect_on_line(
    line_text: str,
    page_number: int,
    mapping: list[tuple[int, int, tuple[float, float, float, float]]],
    categories: set[RedactionCategory] | None,
) -> list[RedactionMatch]:
    matches: list[RedactionMatch] = []

    def add(category: RedactionCategory, span_start: int, span_end: int, text: str) -> None:
        if categories and category not in categories:
            return
        rect = _match_rect(span_start, span_end, mapping)
        if rect is None:
            return
        matches.append(
            RedactionMatch(
                category=category,
                matched_text=text,
                context_before=line_text[max(0, span_start - 60) : span_start],
                context_after=line_text[span_end : span_end + 60],
                page_number=page_number,
                x0=rect[0],
                y0=rect[1],
                x1=rect[2],
                y1=rect[3],
            )
        )

    for pattern, category in (
        (SSN_RE, RedactionCategory.SSN),
        (EMAIL_RE, RedactionCategory.EMAIL),
        (PHONE_RE, RedactionCategory.PHONE),
        (ALNUM_ACCOUNT_RE, RedactionCategory.ACCOUNT_NUMBER),
        (NUMERIC_ACCOUNT_RE, RedactionCategory.ACCOUNT_NUMBER),
    ):
        for m in pattern.finditer(line_text):
            add(category, m.start(), m.end(), m.group())

    for term in MEDICAL_TERMS:
        for m in re.finditer(re.escape(term), line_text, re.IGNORECASE):
            add(RedactionCategory.MEDICAL_TERM, m.start(), m.end(), m.group())

    for m in TWO_WORD_NAME_RE.finditer(line_text):
        first, second = m.group().split(" ", 1)
        if first.lower() in NAME_STOPLIST or second.lower() in NAME_STOPLIST:
            continue
        add(RedactionCategory.NAME, m.start(), m.end(), m.group())

    return matches


def detect_in_pdf(
    pdf_path: str,
    categories: list[RedactionCategory] | None = None,
) -> list[RedactionMatch]:
    """Run the fallback regex engine over a PDF's text layer.

    Words are grouped into visual lines (same rounded baseline); patterns run
    per line; coordinates are resolved from the underlying word rectangles so
    proposals still carry exact PDF spans for byte-scrubbing.
    """
    category_set = set(categories) if categories else None
    results: list[RedactionMatch] = []
    doc = fitz.open(pdf_path)
    try:
        for page_number, page in enumerate(doc, start=1):
            words = page.get_text("words")
            lines: dict[float, list[tuple[str, tuple[float, float, float, float]]]] = {}
            for word_data in words:
                x0, y0, x1, y1, word, *_ = word_data
                baseline = round(y0, 1)
                lines.setdefault(baseline, []).append((word, (x0, y0, x1, y1)))

            for baseline in sorted(lines):
                line_words = lines[baseline]
                line_text = " ".join(w for w, _ in line_words)
                mapping = _word_rects_from_line(line_text, line_words)
                results.extend(_detect_on_line(line_text, page_number, mapping, category_set))
    finally:
        doc.close()
    return results
