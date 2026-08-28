"""Modification agreement extractor.

Extracts term changes from modification/restructuring agreements.
Each term change produces a separate fact group containing:
original_loan_reference, modified_field_name, original_value,
new_value, effective_date.
"""

from __future__ import annotations

import re
from typing import Optional

from src.pipeline.extractors.base import ExtractedFact, SourceSpan


class ModificationExtractor:
    """Extracts term changes from modification agreements.

    Each term change produces a separate fact group:
    original_loan_reference, modified_field_name, original_value,
    new_value, effective_date
    """

    SUPPORTED_FIELDS = [
        "interest_rate",
        "tenure_months",
        "emi_amount",
        "moratorium_period_months",
    ]

    # Patterns for extracting loan references
    _LOAN_REF_PATTERNS = [
        re.compile(
            r"(?:Reference|Ref|Account\s*No|Account\s*Number|Agreement\s*(?:ID|No|Number)|Loan\s*(?:ID|No|Number|A/C))"
            r"\s*[:.#]\s*([A-Za-z0-9][\w\-/]+)",
            re.IGNORECASE,
        ),
    ]

    # Patterns for effective date extraction
    _DATE_PATTERNS = [
        # "Effective Date: 2024-01-15" or "w.e.f. 01/01/2024"
        re.compile(
            r"(?:effective\s*date|w\.?e\.?f\.?|effective\s*from|with\s*effect\s*from)"
            r"\s*[:.]\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})",
            re.IGNORECASE,
        ),
    ]

    # Patterns for interest rate changes
    _RATE_CHANGE_PATTERNS = [
        # "Interest Rate changed from 12% to 10%"
        re.compile(
            r"(?:interest\s*rate|rate\s*of\s*interest)"
            r"[^.]*?(?:changed|revised|reduced|increased|modified|amended)"
            r"[^.]*?from\s*([\d.]+)\s*%?"
            r"\s*(?:to|→)\s*([\d.]+)\s*%?",
            re.IGNORECASE,
        ),
        # "Rate reduced to 10% from 12%"
        re.compile(
            r"(?:interest\s*rate|rate\s*of\s*interest)"
            r"[^.]*?(?:to|→)\s*([\d.]+)\s*%?"
            r"\s*from\s*([\d.]+)\s*%?",
            re.IGNORECASE,
        ),
    ]

    # Patterns for tenure changes
    _TENURE_CHANGE_PATTERNS = [
        # "Tenure extended from 24 months to 36 months"
        re.compile(
            r"(?:tenure|loan\s*(?:tenure|period|term))"
            r"[^.]*?(?:extended|revised|changed|reduced|increased|modified|amended)"
            r"[^.]*?from\s*([\d]+)\s*(?:months?|mths?)?"
            r"\s*(?:to|→)\s*([\d]+)\s*(?:months?|mths?)?",
            re.IGNORECASE,
        ),
    ]

    # Patterns for EMI changes
    _EMI_CHANGE_PATTERNS = [
        # "EMI reduced from ₹5000 to ₹4000" or "EMI changed from 5000 to 4000"
        re.compile(
            r"(?:EMI|equated\s*monthly\s*install?ment)"
            r"[^.]*?(?:reduced|revised|changed|increased|modified|amended)"
            r"[^.]*?from\s*[₹$€£Rs.]*\s*([\d,]+(?:\.\d+)?)"
            r"\s*(?:to|→)\s*[₹$€£Rs.]*\s*([\d,]+(?:\.\d+)?)",
            re.IGNORECASE,
        ),
    ]

    # Patterns for moratorium
    _MORATORIUM_PATTERNS = [
        # "Moratorium of 6 months granted" or "Moratorium period: 6 months"
        re.compile(
            r"(?:moratorium)"
            r"[^.]*?(?:of|period\s*[:.])?\s*([\d]+)\s*(?:months?|mths?)"
            r"[^.]*?(?:granted|approved|provided|given|sanctioned)?",
            re.IGNORECASE,
        ),
    ]

    async def extract(self, text: str, chunks: list[dict]) -> list[ExtractedFact]:
        """Extract modification term changes.

        Groups related fields by fact_group_id.
        Skips changes with unsupported modified_field_name.
        """
        facts: list[ExtractedFact] = []

        # Extract loan reference (shared across all changes)
        loan_ref, loan_ref_span = self._extract_loan_reference(text)

        # Extract effective date (shared across all changes unless per-change)
        effective_date, effective_date_span = self._extract_effective_date(text)

        # Extract individual term changes
        changes = self._extract_changes(text)

        # Build fact groups for each change
        for idx, change in enumerate(changes, start=1):
            group_id = f"change_{idx}"

            # original_loan_reference
            facts.append(
                ExtractedFact(
                    field_name="original_loan_reference",
                    value=loan_ref,
                    confidence=0.9 if loan_ref != "not_found" else 0.0,
                    source_span=loan_ref_span,
                    fact_group_id=group_id,
                )
            )

            # modified_field_name
            facts.append(
                ExtractedFact(
                    field_name="modified_field_name",
                    value=change["field_name"],
                    confidence=change["confidence"],
                    source_span=change["span"],
                    fact_group_id=group_id,
                )
            )

            # original_value
            facts.append(
                ExtractedFact(
                    field_name="original_value",
                    value=change["original_value"],
                    confidence=change["confidence"] if change["original_value"] != "not_found" else 0.0,
                    source_span=change["span"],
                    fact_group_id=group_id,
                )
            )

            # new_value
            facts.append(
                ExtractedFact(
                    field_name="new_value",
                    value=change["new_value"],
                    confidence=change["confidence"] if change["new_value"] != "not_found" else 0.0,
                    source_span=change["span"],
                    fact_group_id=group_id,
                )
            )

            # effective_date
            facts.append(
                ExtractedFact(
                    field_name="effective_date",
                    value=effective_date,
                    confidence=0.9 if effective_date != "not_found" else 0.0,
                    source_span=effective_date_span,
                    fact_group_id=group_id,
                )
            )

        return facts

    def _extract_loan_reference(self, text: str) -> tuple[str, SourceSpan]:
        """Extract the original loan reference from the document."""
        for pattern in self._LOAN_REF_PATTERNS:
            match = pattern.search(text)
            if match:
                value = match.group(1).strip()
                return value, SourceSpan(
                    start_offset=match.start(1),
                    end_offset=match.end(1),
                )
        return "not_found", SourceSpan(start_offset=0, end_offset=1)

    def _extract_effective_date(self, text: str) -> tuple[str, SourceSpan]:
        """Extract the effective date from the document."""
        for pattern in self._DATE_PATTERNS:
            match = pattern.search(text)
            if match:
                raw_date = match.group(1).strip()
                normalized = self._normalize_date(raw_date)
                return normalized, SourceSpan(
                    start_offset=match.start(1),
                    end_offset=match.end(1),
                )
        return "not_found", SourceSpan(start_offset=0, end_offset=1)

    def _normalize_date(self, raw_date: str) -> str:
        """Normalize a date string to ISO 8601 (YYYY-MM-DD)."""
        # Replace separators with a common one
        normalized = raw_date.replace(".", "/").replace("-", "/")
        parts = normalized.split("/")

        if len(parts) != 3:
            return raw_date

        # Determine if format is YYYY/MM/DD or DD/MM/YYYY or MM/DD/YYYY
        if len(parts[0]) == 4:
            # YYYY/MM/DD
            year, month, day = parts[0], parts[1], parts[2]
        elif len(parts[2]) == 4:
            # DD/MM/YYYY (common in India)
            day, month, year = parts[0], parts[1], parts[2]
        elif len(parts[2]) == 2:
            # DD/MM/YY
            day, month = parts[0], parts[1]
            year = "20" + parts[2] if int(parts[2]) < 50 else "19" + parts[2]
        else:
            return raw_date

        try:
            y = int(year)
            m = int(month)
            d = int(day)
            return f"{y:04d}-{m:02d}-{d:02d}"
        except (ValueError, TypeError):
            return raw_date

    def _extract_changes(self, text: str) -> list[dict]:
        """Extract all supported term changes from the text."""
        changes: list[dict] = []

        # Interest rate changes
        for pattern in self._RATE_CHANGE_PATTERNS:
            for match in pattern.finditer(text):
                original = self._normalize_rate(match.group(1))
                new = self._normalize_rate(match.group(2))
                changes.append({
                    "field_name": "interest_rate",
                    "original_value": original,
                    "new_value": new,
                    "confidence": 0.85,
                    "span": SourceSpan(
                        start_offset=match.start(),
                        end_offset=match.end(),
                    ),
                })
            if changes and changes[-1]["field_name"] == "interest_rate":
                break  # Use the first matching pattern

        # Tenure changes
        tenure_found = False
        for pattern in self._TENURE_CHANGE_PATTERNS:
            for match in pattern.finditer(text):
                original = self._normalize_tenure(match.group(1))
                new = self._normalize_tenure(match.group(2))
                changes.append({
                    "field_name": "tenure_months",
                    "original_value": original,
                    "new_value": new,
                    "confidence": 0.85,
                    "span": SourceSpan(
                        start_offset=match.start(),
                        end_offset=match.end(),
                    ),
                })
                tenure_found = True
            if tenure_found:
                break

        # EMI changes
        emi_found = False
        for pattern in self._EMI_CHANGE_PATTERNS:
            for match in pattern.finditer(text):
                original = self._normalize_monetary(match.group(1))
                new = self._normalize_monetary(match.group(2))
                changes.append({
                    "field_name": "emi_amount",
                    "original_value": original,
                    "new_value": new,
                    "confidence": 0.85,
                    "span": SourceSpan(
                        start_offset=match.start(),
                        end_offset=match.end(),
                    ),
                })
                emi_found = True
            if emi_found:
                break

        # Moratorium changes
        moratorium_found = False
        for pattern in self._MORATORIUM_PATTERNS:
            for match in pattern.finditer(text):
                new_value = self._normalize_tenure(match.group(1))
                changes.append({
                    "field_name": "moratorium_period_months",
                    "original_value": "0",
                    "new_value": new_value,
                    "confidence": 0.85,
                    "span": SourceSpan(
                        start_offset=match.start(),
                        end_offset=match.end(),
                    ),
                })
                moratorium_found = True
            if moratorium_found:
                break

        return changes

    def _normalize_rate(self, value: str) -> str:
        """Normalize interest rate to annual percentage with 2 decimal places."""
        try:
            rate = float(value.replace(",", ""))
            return f"{rate:.2f}"
        except (ValueError, TypeError):
            return "not_found"

    def _normalize_tenure(self, value: str) -> str:
        """Normalize tenure/moratorium to whole months as string."""
        try:
            months = int(float(value.replace(",", "")))
            return str(months)
        except (ValueError, TypeError):
            return "not_found"

    def _normalize_monetary(self, value: str) -> str:
        """Normalize monetary values to 2 decimal places."""
        try:
            amount = float(value.replace(",", ""))
            return f"{amount:.2f}"
        except (ValueError, TypeError):
            return "not_found"
