"""Step 8: pricing-lock detection.

Deterministic rule: locate a stated lock/price-protection period and its
expiry date, and compare against a supplied reference evaluation date. This
is the rule that gates step 12 (eligibility) — an active lock must always
result in `not_eligible` and must never allow a contract-edit / amendment
letter to be produced (see `AmendmentLetterData.blocked`).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from src.extraction.text_extraction import find_span, section_for_offset

_LOCK_RE = re.compile(
    r"remain fixed and unamendable for a period of.*?\(the \"Lock Period\"\),"
    r"\s*expiring \**([A-Za-z]+ \d{1,2},\s*\d{4})\**",
)
_NO_LOCK_RE = re.compile(
    r"no minimum pricing lock period", re.IGNORECASE
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _parse_date(raw: str) -> Optional[date]:
    match = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", raw)
    if not match:
        return None
    month_name, day, year = match.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    return date(int(year), month, int(day))


class PricingLockResult:
    def __init__(
        self,
        active: Optional[bool],
        expiry: Optional[str],
        source_span: Optional[str],
        section: Optional[str],
    ) -> None:
        self.active = active
        self.expiry = expiry
        self.source_span = source_span
        self.section = section


def detect_pricing_lock(
    text: str, reference_date: date
) -> PricingLockResult:
    """Step 8: determine whether a pricing lock is active as of reference_date."""

    lock_match = _LOCK_RE.search(text)
    if lock_match:
        expiry_raw = lock_match.group(1)
        expiry_date = _parse_date(expiry_raw)
        active = expiry_date is not None and reference_date < expiry_date
        span_bounds = find_span(text, lock_match.group(0))
        section = section_for_offset(text, span_bounds[0]) if span_bounds else None
        return PricingLockResult(
            active=active,
            expiry=expiry_raw,
            source_span=lock_match.group(0),
            section=section,
        )

    if _NO_LOCK_RE.search(text):
        match = _NO_LOCK_RE.search(text)
        span_bounds = find_span(text, match.group(0))
        section = section_for_offset(text, span_bounds[0]) if span_bounds else None
        return PricingLockResult(
            active=False, expiry=None, source_span=match.group(0), section=section
        )

    return PricingLockResult(active=False, expiry=None, source_span=None, section=None)
