"""Loan agreement fact extractor.

Extracts 9 required fields from loan agreement documents using regex-based
pattern matching: borrower_name, lender_name, principal_amount, interest_rate,
interest_type, tenure_months, repayment_frequency, processing_fee, penal_rate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.pipeline.extractors.base import ExtractedFact, SourceSpan


@dataclass
class _Match:
    """Internal representation of a regex match for a field."""

    value: str
    raw_text: str
    start_offset: int
    end_offset: int


class LoanAgreementExtractor:
    """Extracts structured fields from loan agreements.

    Fields: borrower_name, lender_name, principal_amount, interest_rate,
    interest_type, tenure_months, repayment_frequency, processing_fee, penal_rate
    """

    REQUIRED_FIELDS = [
        "borrower_name",
        "lender_name",
        "principal_amount",
        "interest_rate",
        "interest_type",
        "tenure_months",
        "repayment_frequency",
        "processing_fee",
        "penal_rate",
    ]

    # Regex patterns for each field. Each returns groups for extracting values.
    _BORROWER_PATTERNS = [
        re.compile(
            r"(?:borrower(?:\s+name)?|borrower\s*:)\s*[:\-]?\s*(.+?)(?:\n|$)",
            re.IGNORECASE,
        ),
    ]

    _LENDER_PATTERNS = [
        re.compile(
            r"(?:lender(?:\s+name)?|lender\s*:)\s*[:\-]?\s*(.+?)(?:\n|$)",
            re.IGNORECASE,
        ),
    ]

    _PRINCIPAL_PATTERNS = [
        re.compile(
            r"(?:principal\s+amount|loan\s+amount|principal)\s*[:\-]?\s*"
            r"[₹$€£]?\s*([\d,]+(?:\.\d+)?)",
            re.IGNORECASE,
        ),
    ]

    _INTEREST_RATE_PATTERNS = [
        re.compile(
            r"(?:interest\s+rate|rate\s+of\s+interest)\s*[:\-]?\s*"
            r"([\d]+(?:\.\d+)?)\s*%",
            re.IGNORECASE,
        ),
    ]

    _INTEREST_TYPE_PATTERNS = [
        re.compile(
            r"(flat\s+rate|reducing\s+balance|diminishing\s+balance)",
            re.IGNORECASE,
        ),
    ]

    _TENURE_PATTERNS = [
        re.compile(
            r"(?:tenure|loan\s+period|loan\s+tenure|repayment\s+period)"
            r"\s*[:\-]?\s*(\d+)\s*months?",
            re.IGNORECASE,
        ),
    ]

    _REPAYMENT_FREQ_PATTERNS = [
        re.compile(
            r"(?:repayment\s+frequency|repayment\s+schedule|installment\s+frequency)"
            r"\s*[:\-]?\s*(monthly|quarterly|semi[- ]?annually|annually|bullet)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(monthly|quarterly|semi[- ]?annually|annually|bullet)\s+"
            r"(?:repayment|installment|emi)",
            re.IGNORECASE,
        ),
    ]

    _PROCESSING_FEE_PATTERNS = [
        re.compile(
            r"(?:processing\s+fee|processing\s+charges?)\s*[:\-]?\s*"
            r"[₹$€£]?\s*([\d,]+(?:\.\d+)?)",
            re.IGNORECASE,
        ),
    ]

    _PENAL_RATE_PATTERNS = [
        re.compile(
            r"(?:penal\s+rate|penalty\s+interest|penal\s+interest"
            r"|penalty\s+rate)\s*[:\-]?\s*([\d]+(?:\.\d+)?)\s*%",
            re.IGNORECASE,
        ),
    ]

    async def extract(self, text: str, chunks: list[dict]) -> list[ExtractedFact]:
        """Extract loan agreement fields with source spans.

        For fields not found: value="not_found", confidence=0.0
        For conflicting values: uses last-in-document, confidence <= 0.5
        Normalizes monetary values to 2 decimal places.
        Normalizes rates to annual percentage with 2 decimal places.
        """
        facts: list[ExtractedFact] = []

        for field_name in self.REQUIRED_FIELDS:
            fact = self._extract_field(field_name, text)
            facts.append(fact)

        return facts

    def _extract_field(self, field_name: str, text: str) -> ExtractedFact:
        """Extract a single field from text, handling conflicts and normalization."""
        matches = self._find_all_matches(field_name, text)

        if not matches:
            return ExtractedFact(
                field_name=field_name,
                value="not_found",
                confidence=0.0,
                source_span=None,
            )

        # If multiple matches (conflict), take the last one with confidence <= 0.5
        has_conflict = len(matches) > 1
        match = matches[-1]  # last-in-document

        normalized_value = self._normalize_value(field_name, match.value)
        confidence = 0.5 if has_conflict else 0.85

        return ExtractedFact(
            field_name=field_name,
            value=normalized_value,
            confidence=confidence,
            source_span=SourceSpan(
                start_offset=match.start_offset,
                end_offset=match.end_offset,
            ),
        )

    def _find_all_matches(self, field_name: str, text: str) -> list[_Match]:
        """Find all occurrences of a field in text."""
        patterns = self._get_patterns(field_name)
        all_matches: list[_Match] = []

        for pattern in patterns:
            for m in pattern.finditer(text):
                raw_value = m.group(1).strip()
                all_matches.append(
                    _Match(
                        value=raw_value,
                        raw_text=m.group(0),
                        start_offset=m.start(),
                        end_offset=m.end(),
                    )
                )

        # Sort by position in document (start_offset)
        all_matches.sort(key=lambda x: x.start_offset)
        return all_matches

    def _get_patterns(self, field_name: str) -> list[re.Pattern]:
        """Get regex patterns for a field name."""
        pattern_map = {
            "borrower_name": self._BORROWER_PATTERNS,
            "lender_name": self._LENDER_PATTERNS,
            "principal_amount": self._PRINCIPAL_PATTERNS,
            "interest_rate": self._INTEREST_RATE_PATTERNS,
            "interest_type": self._INTEREST_TYPE_PATTERNS,
            "tenure_months": self._TENURE_PATTERNS,
            "repayment_frequency": self._REPAYMENT_FREQ_PATTERNS,
            "processing_fee": self._PROCESSING_FEE_PATTERNS,
            "penal_rate": self._PENAL_RATE_PATTERNS,
        }
        return pattern_map.get(field_name, [])

    def _normalize_value(self, field_name: str, raw_value: str) -> str:
        """Normalize extracted raw value based on field type."""
        if field_name in ("principal_amount", "processing_fee"):
            return self._normalize_monetary(raw_value)
        elif field_name in ("interest_rate", "penal_rate"):
            return self._normalize_rate(raw_value)
        elif field_name == "interest_type":
            return self._normalize_interest_type(raw_value)
        elif field_name == "tenure_months":
            return raw_value.strip()
        elif field_name == "repayment_frequency":
            return self._normalize_frequency(raw_value)
        else:
            # borrower_name, lender_name: return as-is, trimmed
            return raw_value.strip()

    def _normalize_monetary(self, raw_value: str) -> str:
        """Normalize monetary values to 2 decimal places.

        Removes commas, currency symbols, and formats to exactly 2 decimals.
        """
        # Remove commas and whitespace
        cleaned = raw_value.replace(",", "").strip()
        try:
            amount = float(cleaned)
            return f"{amount:.2f}"
        except ValueError:
            return "not_found"

    def _normalize_rate(self, raw_value: str) -> str:
        """Normalize rates to annual percentage with 2 decimal places."""
        cleaned = raw_value.strip().rstrip("%").strip()
        try:
            rate = float(cleaned)
            return f"{rate:.2f}"
        except ValueError:
            return "not_found"

    def _normalize_interest_type(self, raw_value: str) -> str:
        """Normalize interest type to canonical form."""
        lower = raw_value.lower().strip()
        if "flat" in lower:
            return "flat"
        elif "reducing" in lower or "diminishing" in lower:
            return "reducing_balance"
        return raw_value.strip()

    def _normalize_frequency(self, raw_value: str) -> str:
        """Normalize repayment frequency to canonical form."""
        lower = raw_value.lower().strip()
        if "monthly" in lower:
            return "monthly"
        elif "quarterly" in lower:
            return "quarterly"
        elif "semi" in lower:
            return "semi_annually"
        elif "annually" in lower or "annual" in lower:
            return "annually"
        elif "bullet" in lower:
            return "bullet"
        return raw_value.strip()
