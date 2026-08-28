"""LLM-based fact extractor.

Extracts structured facts from documents using an LLM with structured
multi-field output. Uses the same LLMClient protocol and prompt-separation
pattern as the evaluators: field schema in the static system prompt,
document text in the user prompt between delimiters.

Citation strategy:
- The LLM returns a verbatim quoted span for each extracted field.
- We locate that exact string in the source text programmatically to
  compute character offsets.
- If exact match fails, we try normalized matching (whitespace/case-insensitive).
- If that also fails, we flag the citation as unverifiable (confidence 0.0
  for the span, but the claim is still included).
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from src.pipeline.extractors.base import ExtractedFact, SourceSpan
from src.pipeline.span_resolution import resolve_span

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Protocol for LLM API interaction (same as evaluators.LLMClient)."""

    async def chat(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Send a prompt to the LLM and return a structured response."""
        ...


# ---------------------------------------------------------------------------
# Static system prompt — never contains document content
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM_PROMPT = """\
You are a document fact extractor. You extract structured fields from financial \
documents and return them as a JSON object.

You MUST return a JSON object with a "fields" array. Each element has:
- "field_name": the exact field name from the requested schema
- "value": the normalized extracted value (see normalization rules below)
- "confidence": float 0.0–1.0 indicating extraction confidence
- "quoted_span": the EXACT verbatim text from the document that contains this fact \
(copy-paste, including punctuation and whitespace — do NOT paraphrase or summarize)

Normalization rules:
- Monetary values: remove currency symbols and commas, format to 2 decimal places (e.g., "150000.00")
- Rates/percentages: numeric value only with 2 decimal places (e.g., "18.50")
- Interest type: one of "flat", "reducing_balance"
- Repayment frequency: one of "monthly", "quarterly", "semi_annually", "annually", "bullet"
- Tenure: integer number of months as string (e.g., "24")
- Names: as written in the document, trimmed
- Dates: ISO 8601 format YYYY-MM-DD

If a field cannot be found in the document, set value to "not_found", confidence to 0.0, \
and quoted_span to "".

Return ONLY valid JSON, no additional text."""


# ---------------------------------------------------------------------------
# Field schema definitions per document type
# ---------------------------------------------------------------------------

FIELD_SCHEMAS: dict[str, list[dict[str, str]]] = {
    "loan_agreement": [
        {"field_name": "borrower_name", "description": "Full name of the borrower/client"},
        {"field_name": "lender_name", "description": "Full name of the lending institution"},
        {"field_name": "principal_amount", "description": "Loan principal amount (normalize to 2dp, no currency symbol)"},
        {"field_name": "interest_rate", "description": "Annual interest rate as percentage (normalize to 2dp, no % sign)"},
        {"field_name": "interest_type", "description": "Type of interest calculation: 'flat' or 'reducing_balance'"},
        {"field_name": "tenure_months", "description": "Loan tenure/duration in months (integer as string)"},
        {"field_name": "repayment_frequency", "description": "How often repayments are due: monthly/quarterly/semi_annually/annually/bullet"},
        {"field_name": "processing_fee", "description": "One-time processing/admin fee amount (normalize to 2dp, no currency symbol)"},
        {"field_name": "penal_rate", "description": "Penalty/penal interest rate as percentage (normalize to 2dp, no % sign)"},
    ],
    "modification_agreement": [
        {"field_name": "original_loan_reference", "description": "Reference number of the original loan being modified"},
        {"field_name": "effective_date", "description": "Date the modification takes effect (ISO 8601)"},
        {"field_name": "modified_fields", "description": "JSON array of objects, each with: modified_field_name, original_value, new_value"},
    ],
    "repayment_statement": [
        {"field_name": "loan_reference", "description": "Loan account/reference number"},
        {"field_name": "borrower_name", "description": "Name of the borrower"},
        {"field_name": "interest_rate_applied", "description": "Interest rate applied during statement period (2dp, no %)"},
        {"field_name": "payment_rows", "description": "JSON array of objects, each with: payment_date (ISO), amount_paid (2dp), late_fee (2dp), outstanding_balance (2dp)"},
    ],
}


# ---------------------------------------------------------------------------
# Citation location logic
# ---------------------------------------------------------------------------


def locate_span(quoted_span: str, source_text: str) -> Optional[SourceSpan]:
    """Locate a quoted span in the source text to compute character offsets.

    Delegates to the shared resolver, which tries exact match, normalized
    match, and significant-token anchor matching (the LLM may paraphrase
    the quoted span, e.g. "X is Y" for source "X: Y").

    Args:
        quoted_span: The verbatim text the LLM claims to have found.
        source_text: The full source document text.

    Returns:
        SourceSpan with computed offsets, or None if unverifiable.
    """
    span = resolve_span(quoted_span, source_text)
    if span is None:
        return None
    return SourceSpan(start_offset=span[0], end_offset=span[1])


# ---------------------------------------------------------------------------
# LLM Fact Extractor
# ---------------------------------------------------------------------------


class LLMFactExtractor:
    """Extracts structured facts from documents using an LLM.

    Implements the FactExtractor protocol. Extracts all fields for a
    document type in one LLM call with structured multi-field output.

    Uses the same prompt-separation pattern as the evaluators:
    - Static system prompt defines the extraction schema
    - Document text is passed in the user prompt between --- delimiters
    """

    def __init__(self, llm_client: LLMClient, document_type: str) -> None:
        """Initialize with an LLM client and document type.

        Args:
            llm_client: An implementation of the LLMClient protocol.
            document_type: The classification label (determines which fields to extract).
        """
        self._client = llm_client
        self._document_type = document_type

    async def extract(self, text: str, chunks: list[dict]) -> list[ExtractedFact]:
        """Extract all fields for the document type in one LLM call.

        Args:
            text: The full document text.
            chunks: Chunk metadata (unused for LLM extraction, included for protocol).

        Returns:
            List of ExtractedFact with source spans computed from quoted text.

        Raises:
            Exception: On LLM API failure (propagates to caller for retry).
        """
        if not text or not text.strip():
            return self._empty_facts()

        field_schema = FIELD_SCHEMAS.get(self._document_type, [])
        if not field_schema:
            # Unknown document type — extract with generic prompt
            field_schema = FIELD_SCHEMAS.get("loan_agreement", [])

        user_prompt = self._build_user_prompt(text, field_schema)

        # LLM call — exceptions propagate on failure
        response = await self._client.chat(_EXTRACTION_SYSTEM_PROMPT, user_prompt)

        return self._parse_response(response, text, field_schema)

    async def extract_fields(
        self,
        text: str,
        field_names: list[str],
    ) -> list[ExtractedFact]:
        """Extract specific fields only (used for field-level fallback).

        Args:
            text: The full document text.
            field_names: List of specific field names to extract.

        Returns:
            List of ExtractedFact for the requested fields only.
        """
        if not text or not text.strip():
            return [
                ExtractedFact(
                    field_name=f,
                    value="not_found",
                    confidence=0.0,
                    source_span=None,
                )
                for f in field_names
            ]

        # Build a filtered schema for just the requested fields
        full_schema = FIELD_SCHEMAS.get(self._document_type, [])
        field_schema = [f for f in full_schema if f["field_name"] in field_names]

        # If the requested fields aren't in our schema, create generic entries
        known_names = {f["field_name"] for f in field_schema}
        for name in field_names:
            if name not in known_names:
                field_schema.append({
                    "field_name": name,
                    "description": f"Extract the value for '{name}'",
                })

        user_prompt = self._build_user_prompt(text, field_schema)
        response = await self._client.chat(_EXTRACTION_SYSTEM_PROMPT, user_prompt)
        return self._parse_response(response, text, field_schema)

    def _build_user_prompt(
        self, text: str, field_schema: list[dict[str, str]]
    ) -> str:
        """Build the user prompt with document text between --- delimiters."""
        schema_section = "\n".join(
            f"- {f['field_name']}: {f['description']}"
            for f in field_schema
        )
        return (
            f"Extract the following fields from the document:\n"
            f"{schema_section}\n\n"
            f"Document Text:\n"
            f"---\n"
            f"{text}\n"
            f"---\n\n"
            f"Return the JSON object with the 'fields' array."
        )

    def _parse_response(
        self,
        response: dict[str, Any],
        source_text: str,
        field_schema: list[dict[str, str]],
    ) -> list[ExtractedFact]:
        """Parse the LLM response into ExtractedFact instances.

        Locates quoted spans in source text to compute offsets.
        """
        fields_data = response.get("fields", [])

        # If the response is malformed, return not_found for all fields
        if not isinstance(fields_data, list):
            logger.warning("LLM extraction response malformed: 'fields' is not a list")
            return self._empty_facts_for_schema(field_schema)

        facts: list[ExtractedFact] = []
        seen_fields: set[str] = set()

        for item in fields_data:
            if not isinstance(item, dict):
                continue

            field_name = item.get("field_name", "")
            value = item.get("value", "not_found")
            confidence = item.get("confidence", 0.0)
            quoted_span = item.get("quoted_span", "")

            if not field_name:
                continue

            seen_fields.add(field_name)

            # Locate the quoted span in source text
            span = locate_span(quoted_span, source_text)

            # If span is None (unverifiable) but we have a value, reduce confidence
            if span is None and value != "not_found":
                # Citation unverifiable — flag with reduced confidence
                confidence = min(confidence, 0.5)
                logger.info(
                    "Citation unverifiable for field '%s': quoted span not found in source",
                    field_name,
                )

            facts.append(ExtractedFact(
                field_name=field_name,
                value=str(value) if value is not None else "not_found",
                confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.0,
                source_span=span,
            ))

        # Ensure all schema fields are represented (fill missing with not_found)
        for field_def in field_schema:
            fname = field_def["field_name"]
            if fname not in seen_fields:
                facts.append(ExtractedFact(
                    field_name=fname,
                    value="not_found",
                    confidence=0.0,
                    source_span=None,
                ))

        return facts

    def _empty_facts(self) -> list[ExtractedFact]:
        """Return not_found facts for all fields in the document type schema."""
        field_schema = FIELD_SCHEMAS.get(self._document_type, [])
        return self._empty_facts_for_schema(field_schema)

    def _empty_facts_for_schema(
        self, field_schema: list[dict[str, str]]
    ) -> list[ExtractedFact]:
        """Return not_found facts for a given schema."""
        return [
            ExtractedFact(
                field_name=f["field_name"],
                value="not_found",
                confidence=0.0,
                source_span=None,
            )
            for f in field_schema
        ]
