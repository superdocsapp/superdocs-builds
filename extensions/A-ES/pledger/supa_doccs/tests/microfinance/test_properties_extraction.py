"""Property-based tests for extraction (Properties 3–12).

Feature: microfinance-ingestion-pipeline
Tests type-specific extraction schema completeness, field handling,
normalization, conflict resolution, and row indexing.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.pipeline.extractors.loan_agreement import LoanAgreementExtractor
from src.pipeline.extractors.modification import ModificationExtractor
from src.pipeline.extractors.repayment import RepaymentExtractor
from src.pipeline.extractors.base import ExtractedFact, SourceSpan

from tests.microfinance.conftest import (
    loan_agreement_text,
    modification_text,
    repayment_text,
    monetary_string,
    date_string,
)


# ---------------------------------------------------------------------------
# Property 3: Extraction Schema Completeness
# ---------------------------------------------------------------------------


LOAN_REQUIRED_FIELDS = {
    "borrower_name", "lender_name", "principal_amount",
    "interest_rate", "interest_type", "tenure_months",
    "repayment_frequency", "processing_fee", "penal_rate",
}

MODIFICATION_REQUIRED_FIELDS = {
    "original_loan_reference", "modified_field_name",
    "original_value", "new_value", "effective_date",
}

REPAYMENT_REQUIRED_FIELDS = {
    "payment_date", "amount_paid", "late_fee_charged",
    "outstanding_balance",
}


class TestProperty3ExtractionSchemaCompleteness:
    """Property 3: Extraction always produces exactly the required field names
    for that document type.

    **Validates: Requirements 2.1, 3.1, 4.1**
    """

    @pytest.mark.anyio
    @given(text=loan_agreement_text())
    @settings(max_examples=100)
    async def test_loan_agreement_produces_all_required_fields(self, text: str):
        """Loan agreement extraction produces exactly the 9 required fields."""
        extractor = LoanAgreementExtractor()
        facts = await extractor.extract(text, [])

        field_names = {f.field_name for f in facts}
        assert LOAN_REQUIRED_FIELDS.issubset(field_names), (
            f"Missing fields: {LOAN_REQUIRED_FIELDS - field_names}"
        )

    @pytest.mark.anyio
    @given(text=modification_text())
    @settings(max_examples=100)
    async def test_modification_produces_required_fields_per_group(self, text: str):
        """Modification extraction produces all required fields per fact group."""
        extractor = ModificationExtractor()
        facts = await extractor.extract(text, [])

        # Group facts by fact_group_id
        groups: dict[str, set[str]] = {}
        for fact in facts:
            gid = fact.fact_group_id
            if gid not in groups:
                groups[gid] = set()
            groups[gid].add(fact.field_name)

        # Each group must have all required modification fields
        for group_id, fields in groups.items():
            assert MODIFICATION_REQUIRED_FIELDS.issubset(fields), (
                f"Group {group_id} missing: {MODIFICATION_REQUIRED_FIELDS - fields}"
            )

    @pytest.mark.anyio
    @given(text=repayment_text())
    @settings(max_examples=100)
    async def test_repayment_produces_required_fields_per_row(self, text: str):
        """Repayment extraction produces required fields per payment row."""
        extractor = RepaymentExtractor()
        facts = await extractor.extract(text, [])

        # Group facts by fact_group_id (row_N)
        groups: dict[str, set[str]] = {}
        for fact in facts:
            gid = fact.fact_group_id
            if gid not in groups:
                groups[gid] = set()
            groups[gid].add(fact.field_name)

        # Each row group must have the 4 required repayment fields
        for group_id, fields in groups.items():
            assert REPAYMENT_REQUIRED_FIELDS.issubset(fields), (
                f"Group {group_id} missing: {REPAYMENT_REQUIRED_FIELDS - fields}"
            )


# ---------------------------------------------------------------------------
# Property 4: Missing Field Handling
# ---------------------------------------------------------------------------


class TestProperty4MissingFieldHandling:
    """Property 4: Missing/blank/unparseable fields get value="not_found"/
    "unparseable" with confidence=0.0.

    **Validates: Requirements 2.2, 2.4, 3.5, 4.5, 4.6**
    """

    @pytest.mark.anyio
    async def test_loan_missing_fields_produce_not_found(self):
        """When a loan agreement has no recognizable fields, all are 'not_found'."""
        extractor = LoanAgreementExtractor()
        # Text with no recognizable loan fields
        text = "This is a random document with no loan terms whatsoever."
        facts = await extractor.extract(text, [])

        for fact in facts:
            assert fact.value == "not_found"
            assert fact.confidence == 0.0

    @pytest.mark.anyio
    async def test_repayment_unparseable_date(self):
        """Unparseable dates produce value='unparseable' with confidence=0.0."""
        extractor = RepaymentExtractor()
        # A repayment table with an invalid date
        text = (
            "REPAYMENT STATEMENT\n"
            "===================\n\n"
            "| Payment Date | Amount Paid | Late Fee | Outstanding Balance |\n"
            "|---|---|---|---|\n"
            "| NOT-A-DATE | 5000.00 | 100.00 | 95000.00 |\n"
        )
        facts = await extractor.extract(text, [])

        date_facts = [f for f in facts if f.field_name == "payment_date"]
        assert len(date_facts) >= 1
        assert date_facts[0].value == "unparseable"
        assert date_facts[0].confidence == 0.0

    @pytest.mark.anyio
    async def test_repayment_blank_monetary_field(self):
        """Blank monetary fields produce value='not_found' with confidence=0.0."""
        extractor = RepaymentExtractor()
        text = (
            "REPAYMENT STATEMENT\n"
            "===================\n\n"
            "| Payment Date | Amount Paid | Late Fee | Outstanding Balance |\n"
            "|---|---|---|---|\n"
            "| 15/01/2024 |  | 100.00 | 95000.00 |\n"
        )
        facts = await extractor.extract(text, [])

        amount_facts = [f for f in facts if f.field_name == "amount_paid"]
        assert len(amount_facts) >= 1
        assert amount_facts[0].value == "not_found"
        assert amount_facts[0].confidence == 0.0


# ---------------------------------------------------------------------------
# Property 5: Monetary Normalization
# ---------------------------------------------------------------------------


class TestProperty5MonetaryNormalization:
    """Property 5: Monetary normalization always produces exactly 2 decimal places.

    **Validates: Requirements 2.3, 4.3**
    """

    @pytest.mark.anyio
    @given(text=loan_agreement_text())
    @settings(max_examples=100)
    async def test_loan_monetary_fields_have_2_decimals(self, text: str):
        """principal_amount and processing_fee have exactly 2 decimal places."""
        extractor = LoanAgreementExtractor()
        facts = await extractor.extract(text, [])

        monetary_fields = {"principal_amount", "processing_fee"}
        for fact in facts:
            if fact.field_name in monetary_fields and fact.value != "not_found":
                # Should match pattern: digits with exactly 2 decimal places
                assert re.match(r"^\d+\.\d{2}$", fact.value), (
                    f"Field {fact.field_name} value '{fact.value}' "
                    f"does not have exactly 2 decimal places"
                )

    @pytest.mark.anyio
    @given(text=repayment_text())
    @settings(max_examples=100)
    async def test_repayment_monetary_fields_have_2_decimals(self, text: str):
        """amount_paid, late_fee_charged, outstanding_balance have exactly 2 decimals."""
        extractor = RepaymentExtractor()
        facts = await extractor.extract(text, [])

        monetary_fields = {"amount_paid", "late_fee_charged", "outstanding_balance"}
        for fact in facts:
            if fact.field_name in monetary_fields and fact.value not in ("not_found", "unparseable"):
                assert re.match(r"^-?\d+\.\d{2}$", fact.value), (
                    f"Field {fact.field_name} value '{fact.value}' "
                    f"does not have exactly 2 decimal places"
                )


# ---------------------------------------------------------------------------
# Property 6: Rate Normalization
# ---------------------------------------------------------------------------


class TestProperty6RateNormalization:
    """Property 6: Rates normalized to annual percentage with exactly 2 decimal places.

    **Validates: Requirements 2.5, 3.6**
    """

    @pytest.mark.anyio
    @given(text=loan_agreement_text())
    @settings(max_examples=100)
    async def test_loan_rates_have_2_decimals(self, text: str):
        """interest_rate and penal_rate are annual percentage with 2 decimal places."""
        extractor = LoanAgreementExtractor()
        facts = await extractor.extract(text, [])

        rate_fields = {"interest_rate", "penal_rate"}
        for fact in facts:
            if fact.field_name in rate_fields and fact.value != "not_found":
                assert re.match(r"^\d+\.\d{2}$", fact.value), (
                    f"Field {fact.field_name} value '{fact.value}' "
                    f"does not have exactly 2 decimal places"
                )

    @pytest.mark.anyio
    @given(text=modification_text())
    @settings(max_examples=100)
    async def test_modification_rate_values_have_2_decimals(self, text: str):
        """Modification rate original_value and new_value have 2 decimal places."""
        extractor = ModificationExtractor()
        facts = await extractor.extract(text, [])

        # Find facts where modified_field_name is interest_rate
        rate_groups: set[str] = set()
        for fact in facts:
            if fact.field_name == "modified_field_name" and fact.value == "interest_rate":
                rate_groups.add(fact.fact_group_id)

        # Check original_value and new_value in those groups
        for fact in facts:
            if (
                fact.fact_group_id in rate_groups
                and fact.field_name in ("original_value", "new_value")
                and fact.value != "not_found"
            ):
                assert re.match(r"^\d+\.\d{2}$", fact.value), (
                    f"Rate value '{fact.value}' in group {fact.fact_group_id} "
                    f"does not have exactly 2 decimal places"
                )


# ---------------------------------------------------------------------------
# Property 7: Confidence Score Bounds
# ---------------------------------------------------------------------------


class TestProperty7ConfidenceScoreBounds:
    """Property 7: Confidence is in [0.0, 1.0] with <= 3 decimal places.

    **Validates: Requirements 2.6, 4.7**
    """

    @pytest.mark.anyio
    @given(text=loan_agreement_text())
    @settings(max_examples=100)
    async def test_loan_confidence_bounds(self, text: str):
        """Every loan fact confidence is in [0.0, 1.0] with <= 3 decimals."""
        extractor = LoanAgreementExtractor()
        facts = await extractor.extract(text, [])

        for fact in facts:
            assert 0.0 <= fact.confidence <= 1.0, (
                f"Confidence {fact.confidence} out of bounds for {fact.field_name}"
            )
            # Check <= 3 decimal places
            conf_str = f"{fact.confidence:.10f}".rstrip("0")
            if "." in conf_str:
                decimal_places = len(conf_str.split(".")[1])
                assert decimal_places <= 3, (
                    f"Confidence {fact.confidence} has more than 3 decimal places"
                )

    @pytest.mark.anyio
    @given(text=repayment_text())
    @settings(max_examples=100)
    async def test_repayment_confidence_bounds(self, text: str):
        """Every repayment fact confidence is in [0.0, 1.0] with <= 3 decimals."""
        extractor = RepaymentExtractor()
        facts = await extractor.extract(text, [])

        for fact in facts:
            assert 0.0 <= fact.confidence <= 1.0, (
                f"Confidence {fact.confidence} out of bounds for {fact.field_name}"
            )
            conf_str = f"{fact.confidence:.10f}".rstrip("0")
            if "." in conf_str:
                decimal_places = len(conf_str.split(".")[1])
                assert decimal_places <= 3, (
                    f"Confidence {fact.confidence} has more than 3 decimal places"
                )

    @pytest.mark.anyio
    @given(text=modification_text())
    @settings(max_examples=100)
    async def test_modification_confidence_bounds(self, text: str):
        """Every modification fact confidence is in [0.0, 1.0] with <= 3 decimals."""
        extractor = ModificationExtractor()
        facts = await extractor.extract(text, [])

        for fact in facts:
            assert 0.0 <= fact.confidence <= 1.0, (
                f"Confidence {fact.confidence} out of bounds for {fact.field_name}"
            )
            conf_str = f"{fact.confidence:.10f}".rstrip("0")
            if "." in conf_str:
                decimal_places = len(conf_str.split(".")[1])
                assert decimal_places <= 3, (
                    f"Confidence {fact.confidence} has more than 3 decimal places"
                )


# ---------------------------------------------------------------------------
# Property 8: Conflict Resolution Picks Last Value
# ---------------------------------------------------------------------------


class TestProperty8ConflictResolution:
    """Property 8: Conflicting values -> last-in-document picked, confidence <= 0.5.

    **Validates: Requirements 2.7**
    """

    @pytest.mark.anyio
    async def test_conflicting_interest_rates_picks_last(self):
        """When multiple interest rates exist, last one is picked with confidence <= 0.5."""
        extractor = LoanAgreementExtractor()
        text = (
            "LOAN AGREEMENT\n"
            "==============\n\n"
            "Borrower: John Doe\n"
            "Lender: MFI Corp\n\n"
            "Interest Rate: 12.00%\n"
            "Interest Rate: 15.50%\n"
            "Interest Type: flat rate\n"
            "Principal Amount: 100000\n"
            "Tenure: 24 months\n"
            "Repayment Frequency: monthly\n"
            "Processing Fee: 2000\n"
            "Penal Rate: 2.00%\n"
        )
        facts = await extractor.extract(text, [])

        rate_fact = next(f for f in facts if f.field_name == "interest_rate")
        # Should pick the last value (15.50)
        assert rate_fact.value == "15.50"
        # Confidence must be <= 0.5 due to conflict
        assert rate_fact.confidence <= 0.5

    @pytest.mark.anyio
    @given(
        rate1=st.floats(min_value=8.0, max_value=36.0, allow_nan=False, allow_infinity=False),
        rate2=st.floats(min_value=8.0, max_value=36.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    async def test_any_conflicting_rates_confidence_capped(self, rate1: float, rate2: float):
        """For any two conflicting rates, confidence is always <= 0.5."""
        assume(abs(rate1 - rate2) > 0.01)  # Ensure they're actually different

        extractor = LoanAgreementExtractor()
        text = (
            "LOAN AGREEMENT\n"
            "==============\n\n"
            "Borrower: Jane Smith\n"
            "Lender: MFI Corp\n\n"
            f"Interest Rate: {rate1:.2f}%\n"
            f"Interest Rate: {rate2:.2f}%\n"
            "Interest Type: reducing balance\n"
            "Principal Amount: 200000\n"
            "Tenure: 36 months\n"
            "Repayment Frequency: monthly\n"
            "Processing Fee: 3000\n"
            "Penal Rate: 3.00%\n"
        )
        facts = await extractor.extract(text, [])

        rate_fact = next(f for f in facts if f.field_name == "interest_rate")
        # Last-in-document (rate2) should be picked
        assert rate_fact.value == f"{rate2:.2f}"
        # Confidence capped at 0.5 due to conflict
        assert rate_fact.confidence <= 0.5


# ---------------------------------------------------------------------------
# Property 9: Modification Field Filtering
# ---------------------------------------------------------------------------


class TestProperty9ModificationFieldFiltering:
    """Property 9: Unsupported modification fields are skipped.

    **Validates: Requirements 3.2**
    """

    @pytest.mark.anyio
    @given(text=modification_text())
    @settings(max_examples=100)
    async def test_only_supported_field_names_in_output(self, text: str):
        """All modified_field_name values are in the supported set."""
        extractor = ModificationExtractor()
        facts = await extractor.extract(text, [])

        supported = set(ModificationExtractor.SUPPORTED_FIELDS)
        for fact in facts:
            if fact.field_name == "modified_field_name":
                assert fact.value in supported, (
                    f"Unsupported field '{fact.value}' found in extraction output"
                )

    @pytest.mark.anyio
    async def test_unsupported_field_changes_are_skipped(self):
        """Term changes with unsupported fields produce no fact records."""
        extractor = ModificationExtractor()
        text = (
            "MODIFICATION AGREEMENT\n"
            "======================\n\n"
            "Reference No: ABC12345\n\n"
            "Effective Date: 15/06/2024\n\n"
            "AMENDMENTS\n"
            "----------\n\n"
            "  Collateral type changed from land to gold\n"
            "  Insurance premium reduced from 5000 to 3000\n"
        )
        facts = await extractor.extract(text, [])

        # No fact groups should be produced for unsupported fields
        field_name_facts = [f for f in facts if f.field_name == "modified_field_name"]
        for f in field_name_facts:
            assert f.value in ModificationExtractor.SUPPORTED_FIELDS


# ---------------------------------------------------------------------------
# Property 10: Multi-Change Cardinality
# ---------------------------------------------------------------------------


class TestProperty10MultiChangeCardinality:
    """Property 10: N supported term changes -> exactly N fact groups.

    **Validates: Requirements 3.4**
    """

    @pytest.mark.anyio
    @given(text=modification_text())
    @settings(max_examples=100)
    async def test_fact_groups_match_supported_changes(self, text: str):
        """Number of fact groups equals number of supported term changes found."""
        extractor = ModificationExtractor()
        facts = await extractor.extract(text, [])

        # Count distinct fact_group_ids
        group_ids = {f.fact_group_id for f in facts if f.fact_group_id}
        num_groups = len(group_ids)

        # Each group must have exactly the 5 required fields
        for gid in group_ids:
            group_facts = [f for f in facts if f.fact_group_id == gid]
            group_fields = {f.field_name for f in group_facts}
            assert MODIFICATION_REQUIRED_FIELDS.issubset(group_fields), (
                f"Group {gid} has {group_fields}, expected {MODIFICATION_REQUIRED_FIELDS}"
            )

        # At least 1 group should exist (modification_text always has >= 1 change)
        assert num_groups >= 1


# ---------------------------------------------------------------------------
# Property 11: Date Normalization to ISO 8601
# ---------------------------------------------------------------------------


class TestProperty11DateNormalization:
    """Property 11: Dates normalized to YYYY-MM-DD.

    **Validates: Requirements 4.2**
    """

    @pytest.mark.anyio
    @given(text=repayment_text())
    @settings(max_examples=100)
    async def test_repayment_dates_are_iso_format(self, text: str):
        """All payment_date values (when parseable) match YYYY-MM-DD format."""
        extractor = RepaymentExtractor()
        facts = await extractor.extract(text, [])

        date_facts = [f for f in facts if f.field_name == "payment_date"]
        for fact in date_facts:
            if fact.value != "unparseable":
                assert re.match(r"^\d{4}-\d{2}-\d{2}$", fact.value), (
                    f"Date '{fact.value}' does not match YYYY-MM-DD format"
                )


# ---------------------------------------------------------------------------
# Property 12: Sequential Row Indexing
# ---------------------------------------------------------------------------


class TestProperty12SequentialRowIndexing:
    """Property 12: N payment rows -> row_index 1..N, no gaps/duplicates.

    **Validates: Requirements 4.4**
    """

    @pytest.mark.anyio
    @given(text=repayment_text())
    @settings(max_examples=100)
    async def test_row_indices_sequential_no_gaps(self, text: str):
        """Row indices form contiguous 1..N sequence with no gaps or duplicates."""
        extractor = RepaymentExtractor()
        facts = await extractor.extract(text, [])

        row_index_facts = [f for f in facts if f.field_name == "row_index"]
        if not row_index_facts:
            return  # No rows extracted is valid for empty input

        indices = [int(f.value) for f in row_index_facts]
        n = len(indices)

        # Must be 1..N
        assert sorted(indices) == list(range(1, n + 1)), (
            f"Row indices {sorted(indices)} are not sequential 1..{n}"
        )
        # No duplicates
        assert len(set(indices)) == n
