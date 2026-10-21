"""Step 6: amendment-clause identification.

Locates the block of contract text governing rate amendments and returns it
as a `PricingClause` fact with an exact source span. The fixture corpus was
deliberately built with five structurally distinct numbering conventions
(Article N.N, SECTION N(a), N.N under Recitals, Clause I.N/II.N, section-symbol
§N.N) specifically so a pipeline cannot pattern-match on one fixed layout.
Each contract's clause-heading pattern is therefore matched independently;
there is no cross-document inference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.domain.models import ExtractionMethod, PricingClause, SourceCitation
from src.extraction.text_extraction import section_for_offset

_HEADING_PATTERNS = [
    # "## Article 7 — Rate Amendments" / "## Article 8 — Pricing Stability"
    re.compile(r"^#{1,3}\s*(Article\s+\d+)\s*[—-]\s*(.+)$", re.MULTILINE),
    # "SECTION 4. RATE REVISIONS AND AMENDMENTS"
    re.compile(r"^={5,}\nSECTION\s+(\d+)\.\s*(.+?)\n={5,}", re.MULTILINE),
    # "### 4. Pricing"
    re.compile(r"^#{1,3}\s*(\d+)\.\s+(.+)$", re.MULTILINE),
    # "Clause II.3 Rate Amendments — Mutual Consent Required."
    re.compile(r"^(Clause\s+[IVXLC]+\.\d+)\s+(.+)$", re.MULTILINE),
    # "§4. RATES AND AMENDMENTS"
    re.compile(r"^(§\d+)\.\s+(.+)$", re.MULTILINE),
]

_AMENDMENT_KEYWORDS = re.compile(
    r"amend|rate revis|pricing|rate change", re.IGNORECASE
)


@dataclass(frozen=True)
class ClauseBlock:
    heading: str
    body: str
    start: int
    end: int


def _find_headings(text: str) -> list[tuple[str, int]]:
    """Return (heading_line, start_offset) for every heading-like line in doc order."""

    headings: list[tuple[str, int]] = []
    for pattern in _HEADING_PATTERNS:
        for match in pattern.finditer(text):
            headings.append((match.group(0), match.start()))
    headings.sort(key=lambda item: item[1])
    return headings


def find_amendment_clause_block(text: str) -> Optional[ClauseBlock]:
    """Find the contiguous block of text under the amendment-governing heading."""

    headings = _find_headings(text)
    if not headings:
        return None

    target_idx = None
    for idx, (heading_line, _start) in enumerate(headings):
        if _AMENDMENT_KEYWORDS.search(heading_line):
            target_idx = idx
            break
    if target_idx is None:
        return None

    heading_line, start = headings[target_idx]
    end = headings[target_idx + 1][1] if target_idx + 1 < len(headings) else len(text)
    body = text[start:end].rstrip()
    return ClauseBlock(heading=heading_line.strip(), body=body, start=start, end=end)


def extract_pricing_clause(
    document_id: str,
    text: str,
    current_rates_reference: Optional[str] = None,
    supporting_clauses: tuple[str, ...] = (),
) -> Optional[PricingClause]:
    """Step 6: identify and quote the pricing/amendment clause for a contract."""

    block = find_amendment_clause_block(text)
    if block is None:
        return None

    section = section_for_offset(text, block.start) or block.heading
    citation = SourceCitation(
        document_id=document_id,
        source_span=block.body,
        confidence=0.85,
        extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
        section=section,
    )

    return PricingClause(
        document_id=document_id,
        clause_reference=block.heading,
        current_rates_reference=current_rates_reference,
        citation=citation,
        supporting_clauses=supporting_clauses,
    )
