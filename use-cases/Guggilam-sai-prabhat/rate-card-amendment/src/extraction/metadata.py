"""Step 3: partner and contract metadata extraction.

Deterministic regex rules over contract text. Every field that cannot be
matched stays `None` rather than being guessed (unsupported facts remain
null).
"""

from __future__ import annotations

import re
from typing import Optional

from src.domain.models import ExtractionMethod, PartnerContract, SourceCitation
from src.extraction.text_extraction import find_span, section_for_offset

_GOVERNING_LAW_RE = re.compile(
    r"governed by the laws of (?:the\s+)?(?:State of\s+)?([A-Za-z,\.\s]+?)[\.\n]",
    re.IGNORECASE,
)

_IDENTIFIER_PATTERNS = [
    re.compile(r"Agreement No\.:\**\s*([A-Za-z0-9\-/]+)"),
    re.compile(r"Contract Reference:\s*([A-Za-z0-9\-/]+)"),
    re.compile(r"\*\*Identifier:\*\*\s*([A-Za-z0-9\-/]+)"),
    re.compile(r"Agreement ID:\s*([A-Za-z0-9\-/]+)"),
    re.compile(r"Reference:\s*([A-Za-z0-9\-/]+)"),
]

_DATE_PATTERNS = [
    re.compile(r"\*\*Effective Date:\*\*\s*([A-Za-z]+ \d{1,2},\s*\d{4})"),
    re.compile(r"Dated:\s*(\d{1,2} [A-Za-z]+ \d{4})"),
    re.compile(r"\*\*Contract Date:\*\*\s*([A-Za-z]+ \d{1,2},\s*\d{4})"),
    re.compile(r"Contract Date:\s*(\d{1,2} [A-Za-z]+ \d{4})"),
]

# Matches "Full Legal Name (\"ShortName\")" pairs anywhere in the header,
# tolerating an inner parenthetical in the legal name itself (e.g.
# "Cape Aurora Telecom (Pty) Ltd.").
_QUOTED_PARTY_RE = re.compile(
    r"([A-Za-zÀ-ſ0-9][A-Za-zÀ-ſ0-9 ,.&'\-]*?(?:\([A-Za-z]+\)[A-Za-zÀ-ſ0-9 ,.&'\-]*?)?)"
    r"\s*\(\"([A-Za-z ]+)\"\)"
)
_HEADER_WINDOW_CHARS = 600


def extract_partner_contract(document_id: str, text: str) -> PartnerContract:
    """Extract partner name, our entity, contract date/identifier, governing law."""

    identifier = _first_match(_IDENTIFIER_PATTERNS, text)
    date = _first_match(_DATE_PATTERNS, text)
    law_match = _GOVERNING_LAW_RE.search(text)
    governing_law = law_match.group(1).strip().rstrip(".") if law_match else None

    our_entity, partner_name = _extract_parties(text)

    anchor = identifier or date or partner_name or text[:40]
    span_bounds = find_span(text, anchor) if anchor else None
    section = section_for_offset(text, span_bounds[0]) if span_bounds else None
    confidence = 0.9 if (identifier and date and partner_name) else 0.6

    citation = SourceCitation(
        document_id=document_id,
        source_span=anchor.strip() if anchor else text[:40].strip(),
        confidence=confidence,
        extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
        section=section,
    )

    return PartnerContract(
        document_id=document_id,
        partner_name=partner_name,
        our_entity=our_entity,
        contract_date=date,
        contract_identifier=identifier,
        governing_law=governing_law,
        citation=citation,
    )


def _first_match(patterns: list[re.Pattern[str]], text: str) -> Optional[str]:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _extract_parties(text: str) -> tuple[Optional[str], Optional[str]]:
    """Return (our_entity, partner_name).

    "Our entity" is heuristically the first-named party (the drafting/our
    side appears first in every fixture contract), the second is the partner.
    """

    header = text[:_HEADER_WINDOW_CHARS]
    matches = _QUOTED_PARTY_RE.findall(header)
    if len(matches) < 2:
        return None, None

    def clean(name: str) -> str:
        name = re.sub(r"^(?:and|And|Between:|And:)\s+", "", name.strip())
        return name.strip().rstrip(",")

    first_name = clean(matches[0][0])
    second_name = clean(matches[1][0])
    return first_name, second_name
