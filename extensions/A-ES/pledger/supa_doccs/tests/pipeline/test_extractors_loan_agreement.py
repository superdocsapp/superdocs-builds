"""Unit tests for LoanAgreementExtractor.

Tests extraction of 9 required fields, normalization, missing-field handling,
and conflicting-value resolution.
"""

import pytest

from src.pipeline.extractors.base import ExtractedFact, SourceSpan
from src.pipeline.extractors.loan_agreement import LoanAgreementExtractor


@pytest.fixture
def extractor() -> LoanAgreementExtractor:
    return LoanAgreementExtractor()


@pytest.fixture
def sample_loan_text() -> str:
    return (
        "LOAN AGREEMENT\n"
        "\n"
        "Borrower Name: Rajesh Kumar\n"
        "Lender Name: ABC Microfinance Ltd\n"
        "Principal Amount: ₹1,00,000\n"
        "Interest Rate: 18.50% per annum\n"
        "Interest Type: Reducing Balance\n"
        "Tenure: 24 months\n"
        "Repayment Frequency: Monthly\n"
        "Processing Fee: ₹2,500\n"
        "Penal Rate: 2.00% p.a.\n"
    )


class TestBasicExtraction:
    """Tests for basic field extraction from well-formed documents."""

    @pytest.mark.anyio
    async def test_extracts_all_nine_fields(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        assert len(facts) == 9
        field_names = [f.field_name for f in facts]
        assert field_names == LoanAgreementExtractor.REQUIRED_FIELDS

    @pytest.mark.anyio
    async def test_borrower_name_extraction(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        borrower = next(f for f in facts if f.field_name == "borrower_name")
        assert borrower.value == "Rajesh Kumar"
        assert borrower.confidence > 0.0

    @pytest.mark.anyio
    async def test_lender_name_extraction(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        lender = next(f for f in facts if f.field_name == "lender_name")
        assert lender.value == "ABC Microfinance Ltd"
        assert lender.confidence > 0.0

    @pytest.mark.anyio
    async def test_principal_amount_normalized(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        principal = next(f for f in facts if f.field_name == "principal_amount")
        assert principal.value == "100000.00"
        assert principal.confidence > 0.0

    @pytest.mark.anyio
    async def test_interest_rate_normalized(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        rate = next(f for f in facts if f.field_name == "interest_rate")
        assert rate.value == "18.50"
        assert rate.confidence > 0.0

    @pytest.mark.anyio
    async def test_interest_type_normalized(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        itype = next(f for f in facts if f.field_name == "interest_type")
        assert itype.value == "reducing_balance"

    @pytest.mark.anyio
    async def test_tenure_months(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        tenure = next(f for f in facts if f.field_name == "tenure_months")
        assert tenure.value == "24"

    @pytest.mark.anyio
    async def test_repayment_frequency_normalized(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        freq = next(f for f in facts if f.field_name == "repayment_frequency")
        assert freq.value == "monthly"

    @pytest.mark.anyio
    async def test_processing_fee_normalized(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        fee = next(f for f in facts if f.field_name == "processing_fee")
        assert fee.value == "2500.00"

    @pytest.mark.anyio
    async def test_penal_rate_normalized(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        penal = next(f for f in facts if f.field_name == "penal_rate")
        assert penal.value == "2.00"


class TestMissingFields:
    """Tests for missing field handling (not_found, confidence=0.0)."""

    @pytest.mark.anyio
    async def test_empty_text_all_not_found(
        self, extractor: LoanAgreementExtractor
    ):
        facts = await extractor.extract("", [])
        assert len(facts) == 9
        for fact in facts:
            assert fact.value == "not_found"
            assert fact.confidence == 0.0

    @pytest.mark.anyio
    async def test_partial_document_missing_fields(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Borrower Name: Priya Sharma\nLender: Quick Finance\n"
        facts = await extractor.extract(text, [])
        borrower = next(f for f in facts if f.field_name == "borrower_name")
        assert borrower.value == "Priya Sharma"

        lender = next(f for f in facts if f.field_name == "lender_name")
        assert lender.value == "Quick Finance"

        # All other fields should be not_found
        for fact in facts:
            if fact.field_name not in ("borrower_name", "lender_name"):
                assert fact.value == "not_found"
                assert fact.confidence == 0.0


class TestConflictingValues:
    """Tests for conflicting value resolution (last-in-document, confidence <= 0.5)."""

    @pytest.mark.anyio
    async def test_conflicting_interest_rate_takes_last(
        self, extractor: LoanAgreementExtractor
    ):
        text = (
            "Interest Rate: 12.00% per annum\n"
            "... some clauses ...\n"
            "Revised Interest Rate: 15.00% per annum\n"
        )
        facts = await extractor.extract(text, [])
        rate = next(f for f in facts if f.field_name == "interest_rate")
        assert rate.value == "15.00"
        assert rate.confidence <= 0.5

    @pytest.mark.anyio
    async def test_conflicting_principal_takes_last(
        self, extractor: LoanAgreementExtractor
    ):
        text = (
            "Principal Amount: ₹50,000\n"
            "Corrected Principal Amount: ₹75,000\n"
        )
        facts = await extractor.extract(text, [])
        principal = next(f for f in facts if f.field_name == "principal_amount")
        assert principal.value == "75000.00"
        assert principal.confidence <= 0.5

    @pytest.mark.anyio
    async def test_single_occurrence_high_confidence(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Interest Rate: 12.00% per annum\n"
        facts = await extractor.extract(text, [])
        rate = next(f for f in facts if f.field_name == "interest_rate")
        assert rate.value == "12.00"
        assert rate.confidence > 0.5


class TestNormalization:
    """Tests for value normalization rules."""

    @pytest.mark.anyio
    async def test_monetary_removes_commas(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Principal Amount: 5,00,000\n"
        facts = await extractor.extract(text, [])
        principal = next(f for f in facts if f.field_name == "principal_amount")
        assert principal.value == "500000.00"

    @pytest.mark.anyio
    async def test_monetary_handles_no_decimals(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Processing Fee: 1000\n"
        facts = await extractor.extract(text, [])
        fee = next(f for f in facts if f.field_name == "processing_fee")
        assert fee.value == "1000.00"

    @pytest.mark.anyio
    async def test_rate_with_integer(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Penal Rate: 3% p.a.\n"
        facts = await extractor.extract(text, [])
        penal = next(f for f in facts if f.field_name == "penal_rate")
        assert penal.value == "3.00"

    @pytest.mark.anyio
    async def test_interest_type_flat(
        self, extractor: LoanAgreementExtractor
    ):
        text = "The loan carries a flat rate of interest.\n"
        facts = await extractor.extract(text, [])
        itype = next(f for f in facts if f.field_name == "interest_type")
        assert itype.value == "flat"

    @pytest.mark.anyio
    async def test_interest_type_diminishing_balance(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Interest is computed on diminishing balance basis.\n"
        facts = await extractor.extract(text, [])
        itype = next(f for f in facts if f.field_name == "interest_type")
        assert itype.value == "reducing_balance"

    @pytest.mark.anyio
    async def test_repayment_frequency_quarterly(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Repayment Frequency: Quarterly\n"
        facts = await extractor.extract(text, [])
        freq = next(f for f in facts if f.field_name == "repayment_frequency")
        assert freq.value == "quarterly"

    @pytest.mark.anyio
    async def test_repayment_frequency_semi_annually(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Repayment Frequency: Semi-Annually\n"
        facts = await extractor.extract(text, [])
        freq = next(f for f in facts if f.field_name == "repayment_frequency")
        assert freq.value == "semi_annually"

    @pytest.mark.anyio
    async def test_repayment_frequency_bullet(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Repayment Frequency: Bullet\n"
        facts = await extractor.extract(text, [])
        freq = next(f for f in facts if f.field_name == "repayment_frequency")
        assert freq.value == "bullet"


class TestSourceSpan:
    """Tests for source span correctness."""

    @pytest.mark.anyio
    async def test_source_span_points_to_matched_text(
        self, extractor: LoanAgreementExtractor
    ):
        text = "Borrower Name: John Doe\n"
        facts = await extractor.extract(text, [])
        borrower = next(f for f in facts if f.field_name == "borrower_name")
        span = borrower.source_span
        assert span.start_offset >= 0
        assert span.end_offset > span.start_offset
        # The span should be within the text bounds
        assert span.end_offset <= len(text)
        # The extracted text at the span should contain the value
        matched = text[span.start_offset : span.end_offset]
        assert "John Doe" in matched

    @pytest.mark.anyio
    async def test_not_found_source_span_is_none(
        self, extractor: LoanAgreementExtractor
    ):
        facts = await extractor.extract("nothing relevant here", [])
        for fact in facts:
            assert fact.source_span is None


class TestProtocolCompliance:
    """Tests that the extractor satisfies the FactExtractor protocol."""

    @pytest.mark.anyio
    async def test_returns_list_of_extracted_facts(
        self, extractor: LoanAgreementExtractor
    ):
        facts = await extractor.extract("some text", [])
        assert isinstance(facts, list)
        for fact in facts:
            assert isinstance(fact, ExtractedFact)
            # source_span is Optional[SourceSpan] — None for unverifiable citations
            assert fact.source_span is None or isinstance(fact.source_span, SourceSpan)

    @pytest.mark.anyio
    async def test_confidence_in_valid_range(
        self, extractor: LoanAgreementExtractor, sample_loan_text: str
    ):
        facts = await extractor.extract(sample_loan_text, [])
        for fact in facts:
            assert 0.0 <= fact.confidence <= 1.0
