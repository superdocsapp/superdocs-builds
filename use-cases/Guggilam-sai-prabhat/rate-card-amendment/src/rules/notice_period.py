"""Step 7: notice-period extraction.

Deterministic regex rules over contract text. When the contract states only
a qualitative standard (e.g., "a commercially reasonable period") rather than
a fixed number of days, `notice_period_days` stays `None` — this is not a
missing extraction, it is what the source document actually says.
"""

from __future__ import annotations

import re
from typing import Optional

from src.domain.models import ExtractionMethod, NoticeRequirement, SourceCitation
from src.extraction.clauses import find_amendment_clause_block
from src.extraction.text_extraction import find_span, section_for_offset

_NUMERIC_NOTICE_RE = re.compile(
    r"(?:least\s+)?\**([a-z\-]+|\d+)\s*\((\d+)\)\s*calendar days",
    re.IGNORECASE,
)
_BUSINESS_NOTICE_RE = re.compile(
    r"\**([a-z\-]+|\d+)\s*\((\d+)\)\s*business days",
    re.IGNORECASE,
)
_GENERIC_DAYS_NOTICE_RE = re.compile(
    r"\**([a-z\-]+|\d+)\s*\((\d+)\)\s*days'?\s*(?:written\s+)?notice",
    re.IGNORECASE,
)
_UNDEFINED_NOTICE_RE = re.compile(
    r'"?commercially reasonable period"?', re.IGNORECASE
)

_DELIVERY_EMAIL_RE = re.compile(
    r"delivered by email to the designated commercial contact[^.]*\.", re.IGNORECASE
)
_DELIVERY_COURIER_RE = re.compile(
    r"courier or registered post[^.]*\.", re.IGNORECASE
)
_DELIVERY_WRITTEN_RE = re.compile(r"written notice", re.IGNORECASE)

_OBJECTION_WINDOW_RE = re.compile(
    r"[Uu]nless the receiving Party objects in writing within [^.]*\.",
)
_TERMINATE_INSTEAD_RE = re.compile(
    r"Cape Aurora may, within [^.]*\.",
)
_AFFIRMATIVE_ACCEPT_RE = re.compile(
    r"No rate amendment proposed under Section 4\.3 shall take effect[^.]*\.",
)


def extract_notice_requirement(document_id: str, text: str) -> NoticeRequirement:
    """Step 7: extract notice-period days/type, delivery method, objection window."""

    days: Optional[int] = None
    period_type: Optional[str] = None
    source_span: Optional[str] = None

    block = find_amendment_clause_block(text)
    scoped_text = block.body if block else text

    calendar_match = _NUMERIC_NOTICE_RE.search(scoped_text)
    business_match = _BUSINESS_NOTICE_RE.search(scoped_text)
    undefined_match = _UNDEFINED_NOTICE_RE.search(scoped_text)
    generic_match = _GENERIC_DAYS_NOTICE_RE.search(scoped_text)

    if calendar_match:
        days = int(calendar_match.group(2))
        period_type = "calendar"
        source_span = calendar_match.group(0)
    elif undefined_match:
        days = None
        period_type = (
            "undefined - contract specifies only 'a commercially reasonable "
            "period', not a fixed number of days"
        )
        source_span = undefined_match.group(0)
    elif business_match:
        days = int(business_match.group(2))
        period_type = "business"
        source_span = business_match.group(0)
    elif generic_match:
        days = int(generic_match.group(2))
        period_type = "calendar"
        source_span = generic_match.group(0)

    delivery_method = None
    if _DELIVERY_COURIER_RE.search(text):
        delivery_method = (
            "courier or registered post only; email notice alone is "
            "explicitly NOT sufficient"
        )
    elif _DELIVERY_EMAIL_RE.search(text):
        delivery_method = "email to designated commercial contact, with confirmation of receipt"
    elif undefined_match:
        delivery_method = "not specified in the attached restatement"
    elif _DELIVERY_WRITTEN_RE.search(text):
        delivery_method = "written notice (method not further specified)"

    objection_window = None
    obj_match = _OBJECTION_WINDOW_RE.search(text)
    term_match = _TERMINATE_INSTEAD_RE.search(text)
    accept_match = _AFFIRMATIVE_ACCEPT_RE.search(text)
    if obj_match:
        objection_window = obj_match.group(0)
    elif term_match:
        objection_window = term_match.group(0)
    elif accept_match:
        objection_window = accept_match.group(0)

    anchor = source_span or ""
    span_bounds = find_span(text, anchor) if anchor else None
    section = section_for_offset(text, span_bounds[0]) if span_bounds else None
    confidence = 0.9 if days is not None else (0.7 if period_type else 0.0)

    citation = SourceCitation(
        document_id=document_id,
        source_span=anchor or "no notice-period language located",
        confidence=confidence,
        extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
        section=section,
    )

    return NoticeRequirement(
        document_id=document_id,
        notice_period_days=days,
        notice_period_type=period_type,
        delivery_method=delivery_method,
        objection_window=objection_window,
        citation=citation,
    )
