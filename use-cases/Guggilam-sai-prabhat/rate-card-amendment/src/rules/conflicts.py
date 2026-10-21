"""Step 11: conflict detection.

Deterministic rules mirroring the escalation triggers in
`fixtures/playbooks/contract_review_playbook.md` §4: references to unattached
documents that govern the question being decided, "Reserved"/"[blank]"
markers where substantive content is expected, self-referential
conflict-of-interpretation clauses that don't resolve to one outcome, and
embedded instruction-like text. Any of these produces a `Conflict` fact and
forces eligibility to `requires_review` (step 12) — never resolved by model
reasoning, so escalation is guaranteed even when no model is available.
"""

from __future__ import annotations

import re

from src.domain.models import Conflict, ExtractionMethod, SourceCitation
from src.extraction.text_extraction import find_span, section_for_offset

_UNATTACHED_RE = re.compile(
    r"[^.]*not attached (?:to this copy|hereto)[^.]*\.", re.IGNORECASE
)
_RESERVED_RE = re.compile(
    r"\[Reserved[^\]]*\][^.]*\.", re.IGNORECASE
)
_UNRESOLVED_CONFLICT_RE = re.compile(
    r"the provision shall be treated as unresolved pending mutual clarification",
    re.IGNORECASE,
)
_INJECTION_RE = re.compile(
    r'"AI assistant:[^"]*"'
    r'|\b(?:SYSTEM|ASSISTANT|USER)\s*:\s*\S.*'
    r'|ignore (?:all )?(?:previous|prior|the above) instructions'
    r'|disregard (?:all )?(?:previous|prior|the above)(?: instructions)?',
    re.IGNORECASE,
)


def detect_conflicts(document_id: str, text: str) -> list[Conflict]:
    """Step 11: find unattached-document dependencies, reserved/blank
    substantive clauses, unresolved conflict-of-interpretation outcomes, and
    embedded instruction-like text.

    An embedded instruction-like passage is recorded as a `Conflict` fact
    (a reviewer note) — it is data to report on, never an instruction to
    execute, per playbook §1.2 and §4.
    """

    conflicts: list[Conflict] = []

    for pattern, description in (
        (_UNATTACHED_RE, "references an unattached document governing the question being decided"),
        (_RESERVED_RE, "clause marked 'Reserved' where substantive content is expected"),
        (_UNRESOLVED_CONFLICT_RE, "conflict-of-interpretation clause resolves to an unresolved outcome"),
    ):
        for match in pattern.finditer(text):
            span_bounds = find_span(text, match.group(0))
            section = section_for_offset(text, span_bounds[0]) if span_bounds else None
            conflicts.append(
                Conflict(
                    document_id=document_id,
                    description=description,
                    citation=SourceCitation(
                        document_id=document_id,
                        source_span=match.group(0).strip(),
                        confidence=0.85,
                        extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
                        section=section,
                    ),
                )
            )

    injection_match = _INJECTION_RE.search(text)
    if injection_match:
        span_bounds = find_span(text, injection_match.group(0))
        section = section_for_offset(text, span_bounds[0]) if span_bounds else None
        conflicts.append(
            Conflict(
                document_id=document_id,
                description=(
                    "embedded instruction-like text detected; recorded verbatim as "
                    "contract data only, not acted upon"
                ),
                citation=SourceCitation(
                    document_id=document_id,
                    source_span=injection_match.group(0),
                    confidence=1.0,
                    extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
                    section=section,
                ),
            )
        )

    return conflicts


def has_prompt_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))
