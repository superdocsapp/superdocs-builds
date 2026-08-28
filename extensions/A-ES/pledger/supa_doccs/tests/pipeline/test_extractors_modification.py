"""Unit tests for ModificationExtractor."""

import pytest

from src.pipeline.extractors.base import ExtractedFact, SourceSpan
from src.pipeline.extractors.modification import ModificationExtractor


@pytest.fixture
def extractor() -> ModificationExtractor:
    return ModificationExtractor()


class TestModificationExtractor:
    """Tests for ModificationExtractor.extract()."""

    @pytest.mark.anyio
    async def test_single_interest_rate_change(self, extractor: ModificationExtractor):
        """Extract a single interest rate change with loan ref and date."""
        text = (
            "Modification Agreement\n"
            "Reference: LOAN-12345\n"
            "Interest Rate changed from 12% to 10%\n"
            "Effective Date: 2024-01-15\n"
        )
        facts = await extractor.extract(text, [])

        assert len(facts) == 5  # one group of 5 facts

        # All facts share same group_id
        group_ids = {f.fact_group_id for f in facts}
        assert group_ids == {"change_1"}

        # Check field names
        field_names = [f.field_name for f in facts]
        assert field_names == [
            "original_loan_reference",
            "modified_field_name",
            "original_value",
            "new_value",
            "effective_date",
        ]

        # Check values
        facts_by_field = {f.field_name: f for f in facts}
        assert facts_by_field["original_loan_reference"].value == "LOAN-12345"
        assert facts_by_field["modified_field_name"].value == "interest_rate"
        assert facts_by_field["original_value"].value == "12.00"
        assert facts_by_field["new_value"].value == "10.00"
        assert facts_by_field["effective_date"].value == "2024-01-15"

    @pytest.mark.anyio
    async def test_tenure_change(self, extractor: ModificationExtractor):
        """Extract tenure extension."""
        text = (
            "Loan Modification Document\n"
            "Account No: ACC-67890\n"
            "Tenure extended from 24 months to 36 months\n"
            "Effective Date: 15/03/2024\n"
        )
        facts = await extractor.extract(text, [])

        facts_by_field = {f.field_name: f for f in facts}
        assert facts_by_field["original_loan_reference"].value == "ACC-67890"
        assert facts_by_field["modified_field_name"].value == "tenure_months"
        assert facts_by_field["original_value"].value == "24"
        assert facts_by_field["new_value"].value == "36"
        assert facts_by_field["effective_date"].value == "2024-03-15"

    @pytest.mark.anyio
    async def test_emi_change(self, extractor: ModificationExtractor):
        """Extract EMI amount change."""
        text = (
            "Amendment Letter\n"
            "Agreement ID: AGR/2023/001\n"
            "EMI reduced from ₹5000 to ₹4000\n"
            "Effective Date: 2024-06-01\n"
        )
        facts = await extractor.extract(text, [])

        facts_by_field = {f.field_name: f for f in facts}
        assert facts_by_field["original_loan_reference"].value == "AGR/2023/001"
        assert facts_by_field["modified_field_name"].value == "emi_amount"
        assert facts_by_field["original_value"].value == "5000.00"
        assert facts_by_field["new_value"].value == "4000.00"

    @pytest.mark.anyio
    async def test_moratorium_granted(self, extractor: ModificationExtractor):
        """Extract moratorium period grant."""
        text = (
            "Restructuring Agreement\n"
            "Loan No: MF-2024-555\n"
            "Moratorium of 6 months granted\n"
            "Effective Date: 01/04/2024\n"
        )
        facts = await extractor.extract(text, [])

        facts_by_field = {f.field_name: f for f in facts}
        assert facts_by_field["modified_field_name"].value == "moratorium_period_months"
        assert facts_by_field["original_value"].value == "0"
        assert facts_by_field["new_value"].value == "6"

    @pytest.mark.anyio
    async def test_multiple_changes_produce_multiple_groups(self, extractor: ModificationExtractor):
        """Multiple supported changes each produce a separate fact group."""
        text = (
            "Modification Agreement\n"
            "Reference: LOAN-99999\n"
            "Interest Rate revised from 14.5% to 11.0%\n"
            "Tenure extended from 12 months to 24 months\n"
            "EMI changed from ₹10,000 to ₹6,500\n"
            "Effective Date: 2024-02-20\n"
        )
        facts = await extractor.extract(text, [])

        # 3 changes × 5 fields = 15 facts
        assert len(facts) == 15

        # 3 unique group IDs
        group_ids = sorted({f.fact_group_id for f in facts})
        assert group_ids == ["change_1", "change_2", "change_3"]

        # Check each group has 5 facts
        for gid in group_ids:
            group_facts = [f for f in facts if f.fact_group_id == gid]
            assert len(group_facts) == 5

    @pytest.mark.anyio
    async def test_unsupported_field_is_skipped(self, extractor: ModificationExtractor):
        """Unsupported modifications (e.g., processing fee) are not extracted."""
        text = (
            "Modification Agreement\n"
            "Reference: LOAN-11111\n"
            "Processing fee reduced from 2% to 1%\n"
            "Effective Date: 2024-05-10\n"
        )
        facts = await extractor.extract(text, [])

        # No supported changes found → no facts
        assert len(facts) == 0

    @pytest.mark.anyio
    async def test_missing_loan_reference(self, extractor: ModificationExtractor):
        """Missing loan reference produces value='not_found' with confidence 0.0."""
        text = (
            "Modification Agreement\n"
            "Interest Rate changed from 15% to 12%\n"
            "Effective Date: 2024-01-01\n"
        )
        facts = await extractor.extract(text, [])

        facts_by_field = {f.field_name: f for f in facts}
        assert facts_by_field["original_loan_reference"].value == "not_found"
        assert facts_by_field["original_loan_reference"].confidence == 0.0

    @pytest.mark.anyio
    async def test_missing_effective_date(self, extractor: ModificationExtractor):
        """Missing effective date produces value='not_found' with confidence 0.0."""
        text = (
            "Modification Agreement\n"
            "Reference: LOAN-22222\n"
            "Interest Rate changed from 18% to 15%\n"
        )
        facts = await extractor.extract(text, [])

        facts_by_field = {f.field_name: f for f in facts}
        assert facts_by_field["effective_date"].value == "not_found"
        assert facts_by_field["effective_date"].confidence == 0.0

    @pytest.mark.anyio
    async def test_rate_normalization_to_two_decimals(self, extractor: ModificationExtractor):
        """Interest rates are normalized to 2 decimal places."""
        text = (
            "Agreement No: LN-001\n"
            "Interest Rate changed from 12 to 9.5\n"
            "Effective Date: 2024-01-01\n"
        )
        facts = await extractor.extract(text, [])

        facts_by_field = {f.field_name: f for f in facts}
        assert facts_by_field["original_value"].value == "12.00"
        assert facts_by_field["new_value"].value == "9.50"

    @pytest.mark.anyio
    async def test_emi_normalization_with_commas(self, extractor: ModificationExtractor):
        """EMI amounts with commas are normalized to 2 decimal places."""
        text = (
            "Ref: LOAN-333\n"
            "EMI reduced from ₹15,000 to ₹12,500.50\n"
            "Effective Date: 2024-03-01\n"
        )
        facts = await extractor.extract(text, [])

        facts_by_field = {f.field_name: f for f in facts}
        assert facts_by_field["original_value"].value == "15000.00"
        assert facts_by_field["new_value"].value == "12500.50"

    @pytest.mark.anyio
    async def test_source_span_points_to_text(self, extractor: ModificationExtractor):
        """SourceSpan offsets point to meaningful text regions."""
        text = (
            "Modification Agreement\n"
            "Reference: LOAN-ABC\n"
            "Interest Rate changed from 10% to 8%\n"
            "Effective Date: 2024-07-01\n"
        )
        facts = await extractor.extract(text, [])

        for fact in facts:
            span = fact.source_span
            assert span.start_offset < span.end_offset
            assert span.start_offset >= 0
            assert span.end_offset <= len(text)

    @pytest.mark.anyio
    async def test_wef_date_format(self, extractor: ModificationExtractor):
        """w.e.f. date format is recognized."""
        text = (
            "Loan No: MF-100\n"
            "Interest Rate revised from 20% to 16%\n"
            "w.e.f. 01/06/2024\n"
        )
        facts = await extractor.extract(text, [])

        facts_by_field = {f.field_name: f for f in facts}
        assert facts_by_field["effective_date"].value == "2024-06-01"

    @pytest.mark.anyio
    async def test_no_changes_found_returns_empty(self, extractor: ModificationExtractor):
        """Document with no recognizable changes returns empty list."""
        text = (
            "This is a general notice about account maintenance.\n"
            "Please contact our office for details.\n"
        )
        facts = await extractor.extract(text, [])
        assert facts == []

    @pytest.mark.anyio
    async def test_confidence_scores_within_bounds(self, extractor: ModificationExtractor):
        """All confidence scores are between 0.0 and 1.0."""
        text = (
            "Reference: LOAN-777\n"
            "Interest Rate changed from 11% to 9%\n"
            "Tenure extended from 18 months to 30 months\n"
            "Effective Date: 2024-08-15\n"
        )
        facts = await extractor.extract(text, [])

        for fact in facts:
            assert 0.0 <= fact.confidence <= 1.0

    @pytest.mark.anyio
    async def test_supported_fields_constant(self, extractor: ModificationExtractor):
        """SUPPORTED_FIELDS contains exactly the expected values."""
        assert extractor.SUPPORTED_FIELDS == [
            "interest_rate",
            "tenure_months",
            "emi_amount",
            "moratorium_period_months",
        ]
