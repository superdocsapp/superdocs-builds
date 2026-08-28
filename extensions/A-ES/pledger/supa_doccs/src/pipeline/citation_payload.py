"""Canonical approval-queue source-citation builder.

Every code path that enqueues an item into the approval queue MUST build
its ``source_citations`` entries through :func:`build_source_citation`.
This is the single place that:

- attaches document identity (document_id + document_version_id) — a
  citation without a document reference is not a citation for audit
  purposes, because character spans are meaningless once documents can
  be re-uploaded or live in multi-document piles;
- resolves the human-readable snippet by slicing the stored source text
  at the persisted offsets — reviewers must read the quoted text, not
  resolve offset numbers by hand;
- degrades corrupt spans to unverifiable (same rule as the facts API):
  a span is grounded only when ``0 <= start < end``, and when source text
  is available, only when it fits inside that text.

Note on the legacy ``(0, 0)`` sentinel: extract_claims marks missing
spans as ``start_offset=0, end_offset=0`` with
``citation_status="unverifiable"``. This builder treats any zero-width
or inverted span as unverifiable regardless of the claimed status, so
the sentinel can never masquerade as a real location.
"""

from __future__ import annotations

from typing import Any, Optional

# Normalized provenance buckets for trust calibration (Prompt 4.3):
# a reviewer must be able to tell deterministic evaluation from LLM
# evaluation. Fallback paths preserve their underlying nature.
_DETERMINISTIC_METHODS = {"structured", "regex", "regex_fallback"}
_LLM_METHODS = {"llm", "llm_fallback"}


def resolve_evaluation_method(
    claim: dict[str, Any],
    claim_findings: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Resolve how this claim's finding was actually evaluated.

    Traces the real dispatch path (Prompt 4.3) rather than assuming:

    1. Rule-evaluation provenance wins: if a claim-linked finding recorded
       its ``evaluation_method`` (structured check_type vs LLM path from
       match_rules / match_rules_against_sources), that is what produced
       the verdict — use it.
    2. Otherwise fall back to the claim's own extraction method
       (``_extraction_method`` in state / ``extraction_method`` persisted),
       i.e. however the claim itself was actually produced:
       structured/regex → "structured"; llm/llm_fallback → "llm".
    3. Only when nothing recorded either do we return "unknown" — never
       silently claim "llm" (or anything else) by default.
    """
    for finding in claim_findings or []:
        if not isinstance(finding, dict):
            continue
        if finding.get("claim_id") != claim.get("claim_id"):
            continue
        method = finding.get("evaluation_method")
        if method:
            return str(method)

    method = claim.get("_extraction_method") or claim.get("extraction_method")
    if method in _DETERMINISTIC_METHODS:
        return "structured"
    if method in _LLM_METHODS:
        return "llm"
    if method:
        return str(method)
    return "unknown"


def _valid_span(start: Any, end: Any) -> bool:
    try:
        s, e = int(start), int(end)
    except (TypeError, ValueError):
        return False
    return 0 <= s < e


def build_source_citation(
    claim: dict[str, Any],
    *,
    document_id: Optional[str],
    document_version_id: Optional[str],
    extracted_text: Optional[str] = None,
    page_number: Optional[int] = None,
    section_id: Optional[str] = None,
    clause_ref: Optional[str] = None,
    context_chars: int = 60,
) -> dict[str, Any]:
    """Build one canonical source_citation dict from a state-level claim.

    Args:
        claim: Claim dict with claim_id/claim_text/citation_status and,
            for grounded claims, start_offset/end_offset.
        document_id: Document the claim was extracted from.
        document_version_id: Exact version the offsets refer to.
        extracted_text: The full source text of that version; when given,
            the snippet is sliced from it and out-of-range spans degrade
            to unverifiable.
        page_number / section_id / clause_ref: Optional richer location
            metadata when known.
        context_chars: Characters of surrounding context kept around the
            snippet (split into before/after fields).

    Returns:
        Dict matching the frontend SourceCitation shape, including
        document_id, document_version_id, snippet and context fields.
    """
    status = claim.get("citation_status", "grounded")
    start = claim.get("start_offset", 0)
    end = claim.get("end_offset", 0)

    fits_text = (
        extracted_text is None
        or (_valid_span(start, end) and int(end) <= len(extracted_text))
    )
    grounded = status != "unverifiable" and _valid_span(start, end) and fits_text

    citation: dict[str, Any] = {
        "claim_id": claim.get("claim_id"),
        "claim_text": claim.get("claim_text"),
        "citation_status": "grounded" if grounded else "unverifiable",
        "source_location": {
            "page_number": page_number,
            "section_id": section_id,
            "start_offset": int(start),
            "end_offset": int(end),
            "clause_ref": clause_ref,
        }
        if grounded
        else None,
        # Audit identity: WHICH document/version the span points into.
        "document_id": str(document_id) if document_id else None,
        "document_version_id": str(document_version_id)
        if document_version_id
        else None,
        "snippet": None,
        "snippet_context_before": None,
        "snippet_context_after": None,
    }

    if grounded and extracted_text is not None:
        s, e = int(start), int(end)
        citation["snippet"] = extracted_text[s:e]
        citation["snippet_context_before"] = extracted_text[
            max(0, s - context_chars) : s
        ]
        citation["snippet_context_after"] = extracted_text[
            e : min(len(extracted_text), e + context_chars)
        ]

    return citation


def build_source_citations(
    claims: list[dict[str, Any]],
    *,
    document_id: Optional[str],
    document_version_id: Optional[str],
    extracted_text: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Build citations for a list of state-level claims (see builder above)."""
    return [
        build_source_citation(
            c,
            document_id=document_id,
            document_version_id=document_version_id,
            extracted_text=extracted_text,
        )
        for c in claims
    ]
