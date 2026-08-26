"""Step 9: mutual-consent detection.

Deterministic rule: does the contract require both parties' signed consent
for a rate amendment to bind (as opposed to unilateral notice-only)? This
gates step 12 — mutual-consent contracts must resolve to
`not_eligible_unilaterally` and must never produce a unilateral amendment
letter.
"""

from __future__ import annotations

import re
from typing import Optional

from src.extraction.text_extraction import find_span, section_for_offset

_MUTUAL_CONSENT_RE = re.compile(
    r"signed by an authorized representative of BOTH[^.]*\.", re.IGNORECASE
)
_NOTICE_INSUFFICIENT_RE = re.compile(
    r"invitation to negotiate only[^.]*\.", re.IGNORECASE
)


class MutualConsentResult:
    def __init__(self, required: Optional[bool], source_span: Optional[str], section: Optional[str]) -> None:
        self.required = required
        self.source_span = source_span
        self.section = section


def detect_mutual_consent(text: str) -> MutualConsentResult:
    """Step 9: True if the contract text requires both-party signed consent."""

    match = _MUTUAL_CONSENT_RE.search(text) or _NOTICE_INSUFFICIENT_RE.search(text)
    if not match:
        return MutualConsentResult(required=False, source_span=None, section=None)

    span_bounds = find_span(text, match.group(0))
    section = section_for_offset(text, span_bounds[0]) if span_bounds else None
    return MutualConsentResult(required=True, source_span=match.group(0), section=section)
