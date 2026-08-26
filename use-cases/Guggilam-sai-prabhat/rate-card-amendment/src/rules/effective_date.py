"""Step 10: effective-date validation.

Deterministic rule: confirm how a contract ties rate/amendment effectiveness
to a controlling date (e.g. "as of the Effective Date", a lock-period
anchor, "not earlier than the date of last signature"), and whether that
rule can be evaluated from the attached document alone.
"""

from __future__ import annotations

import re
from typing import Optional

from src.extraction.text_extraction import find_span, section_for_offset

_EFFECTIVE_DATE_RULES = [
    re.compile(r"[Rr]ates? for the Services are set forth in the Rate Card[^.]*\."),
    re.compile(r"shall specify its own effective date, which shall not be earlier than the date of the last signature\."),
    re.compile(r"rates? applicable at signing are those in the attached Rate Schedule[^.]*\."),
    re.compile(r"current controlling rate version cannot be determined from this document alone"),
]


class EffectiveDateResult:
    def __init__(self, determinable: bool, source_span: Optional[str], section: Optional[str]) -> None:
        self.determinable = determinable
        self.source_span = source_span
        self.section = section


def validate_effective_date(text: str) -> EffectiveDateResult:
    """Step 10: True if the controlling effective-date rule is determinable
    from the attached document text alone."""

    for pattern in _EFFECTIVE_DATE_RULES:
        match = pattern.search(text)
        if match:
            determinable = "cannot be determined" not in match.group(0)
            span_bounds = find_span(text, match.group(0))
            section = section_for_offset(text, span_bounds[0]) if span_bounds else None
            return EffectiveDateResult(
                determinable=determinable, source_span=match.group(0), section=section
            )

    return EffectiveDateResult(determinable=True, source_span=None, section=None)
