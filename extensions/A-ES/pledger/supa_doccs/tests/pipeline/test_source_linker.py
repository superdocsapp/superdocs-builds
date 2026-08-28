"""Unit tests for SourceLinker.

Tests attach/resolve operations, validation, and error handling
for source pointer provenance.
"""

import uuid

import pytest

from src.models.claims import SourceLocation
from src.pipeline.extractors.base import ExtractedFact, SourceSpan
from src.pipeline.source_linker import SourceLinker, SourceResolutionError


@pytest.fixture
def linker() -> SourceLinker:
    return SourceLinker()


@pytest.fixture
def document_version_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_fact() -> ExtractedFact:
    return ExtractedFact(
        field_name="borrower_name",
        value="Rajesh Kumar",
        confidence=0.95,
        source_span=SourceSpan(
            start_offset=10,
            end_offset=22,
            page_number=1,
            section_id="header",
        ),
        fact_group_id="loan_terms",
    )


class TestAttach:
    """Tests for SourceLinker.attach method."""

    def test_attach_creates_source_location(
        self, linker: SourceLinker, sample_fact: ExtractedFact, document_version_id: str
    ):
        result = linker.attach(sample_fact, document_version_id)
        assert isinstance(result, SourceLocation)

    def test_attach_sets_document_version_id(
        self, linker: SourceLinker, sample_fact: ExtractedFact, document_version_id: str
    ):
        result = linker.attach(sample_fact, document_version_id)
        assert result.document_version_id == uuid.UUID(document_version_id)

    def test_attach_sets_page_number(
        self, linker: SourceLinker, sample_fact: ExtractedFact, document_version_id: str
    ):
        result = linker.attach(sample_fact, document_version_id)
        assert result.page_number == 1

    def test_attach_sets_section_id(
        self, linker: SourceLinker, sample_fact: ExtractedFact, document_version_id: str
    ):
        result = linker.attach(sample_fact, document_version_id)
        assert result.section_id == "header"

    def test_attach_sets_offsets(
        self, linker: SourceLinker, sample_fact: ExtractedFact, document_version_id: str
    ):
        result = linker.attach(sample_fact, document_version_id)
        assert result.start_offset == 10
        assert result.end_offset == 22

    def test_attach_sets_clause_ref_from_fact_group_id(
        self, linker: SourceLinker, sample_fact: ExtractedFact, document_version_id: str
    ):
        result = linker.attach(sample_fact, document_version_id)
        assert result.clause_ref == "loan_terms"

    def test_attach_clause_ref_none_when_no_fact_group_id(
        self, linker: SourceLinker, document_version_id: str
    ):
        fact = ExtractedFact(
            field_name="interest_rate",
            value="18.50",
            confidence=0.9,
            source_span=SourceSpan(start_offset=0, end_offset=5),
            fact_group_id=None,
        )
        result = linker.attach(fact, document_version_id)
        assert result.clause_ref is None

    def test_attach_page_number_none_when_not_set(
        self, linker: SourceLinker, document_version_id: str
    ):
        fact = ExtractedFact(
            field_name="interest_rate",
            value="18.50",
            confidence=0.9,
            source_span=SourceSpan(start_offset=0, end_offset=5),
        )
        result = linker.attach(fact, document_version_id)
        assert result.page_number is None
        assert result.section_id is None

    def test_attach_raises_value_error_when_start_equals_end(
        self, linker: SourceLinker, document_version_id: str
    ):
        fact = ExtractedFact(
            field_name="borrower_name",
            value="Test",
            confidence=0.8,
            source_span=SourceSpan(start_offset=5, end_offset=5),
        )
        with pytest.raises(ValueError, match="start_offset.*must be strictly less than"):
            linker.attach(fact, document_version_id)

    def test_attach_raises_value_error_when_start_greater_than_end(
        self, linker: SourceLinker, document_version_id: str
    ):
        fact = ExtractedFact(
            field_name="borrower_name",
            value="Test",
            confidence=0.8,
            source_span=SourceSpan(start_offset=10, end_offset=5),
        )
        with pytest.raises(ValueError, match="start_offset.*must be strictly less than"):
            linker.attach(fact, document_version_id)

    def test_attach_does_not_set_claim_id(
        self, linker: SourceLinker, sample_fact: ExtractedFact, document_version_id: str
    ):
        """claim_id is not set at attach time — it's set during persist_fact."""
        result = linker.attach(sample_fact, document_version_id)
        # claim_id should not be explicitly set by attach
        # It will remain unset until persist_fact assigns it
        assert not hasattr(result, "_claim_id_set_by_attach")


class TestResolve:
    """Tests for SourceLinker.resolve method."""

    def test_resolve_returns_correct_substring(
        self, linker: SourceLinker, sample_fact: ExtractedFact, document_version_id: str
    ):
        stored_text = "Borrower: Rajesh Kumar lives here"
        source_loc = linker.attach(sample_fact, document_version_id)
        # Override offsets for this test to match stored_text
        source_loc.start_offset = 10
        source_loc.end_offset = 22
        result = linker.resolve(source_loc, stored_text)
        assert result == "Rajesh Kumar"

    def test_resolve_returns_full_text_when_span_covers_all(
        self, linker: SourceLinker, document_version_id: str
    ):
        stored_text = "Hello World"
        fact = ExtractedFact(
            field_name="test",
            value="Hello World",
            confidence=1.0,
            source_span=SourceSpan(start_offset=0, end_offset=11),
        )
        source_loc = linker.attach(fact, document_version_id)
        result = linker.resolve(source_loc, stored_text)
        assert result == "Hello World"

    def test_resolve_returns_single_character(
        self, linker: SourceLinker, document_version_id: str
    ):
        stored_text = "ABCDE"
        fact = ExtractedFact(
            field_name="test",
            value="C",
            confidence=1.0,
            source_span=SourceSpan(start_offset=2, end_offset=3),
        )
        source_loc = linker.attach(fact, document_version_id)
        result = linker.resolve(source_loc, stored_text)
        assert result == "C"

    def test_resolve_raises_error_for_end_offset_out_of_bounds(
        self, linker: SourceLinker, document_version_id: str
    ):
        stored_text = "short"
        fact = ExtractedFact(
            field_name="test",
            value="X",
            confidence=1.0,
            source_span=SourceSpan(start_offset=0, end_offset=100),
        )
        source_loc = linker.attach(fact, document_version_id)
        # Set a claim_id and id for the error message
        source_loc.claim_id = uuid.uuid4()
        source_loc.id = uuid.uuid4()

        with pytest.raises(SourceResolutionError) as exc_info:
            linker.resolve(source_loc, stored_text)

        assert "offsets" in exc_info.value.reason
        assert "exceed" in exc_info.value.reason

    def test_resolve_raises_error_for_start_offset_out_of_bounds(
        self, linker: SourceLinker, document_version_id: str
    ):
        stored_text = "short"
        fact = ExtractedFact(
            field_name="test",
            value="X",
            confidence=1.0,
            source_span=SourceSpan(start_offset=50, end_offset=100),
        )
        source_loc = linker.attach(fact, document_version_id)
        source_loc.claim_id = uuid.uuid4()
        source_loc.id = uuid.uuid4()

        with pytest.raises(SourceResolutionError) as exc_info:
            linker.resolve(source_loc, stored_text)

        assert "exceed" in exc_info.value.reason

    def test_resolve_raises_error_for_missing_document_version_id(
        self, linker: SourceLinker, document_version_id: str
    ):
        stored_text = "some text"
        fact = ExtractedFact(
            field_name="test",
            value="some",
            confidence=1.0,
            source_span=SourceSpan(start_offset=0, end_offset=4),
        )
        source_loc = linker.attach(fact, document_version_id)
        # Simulate missing document_version_id
        source_loc.document_version_id = None
        source_loc.claim_id = uuid.uuid4()
        source_loc.id = uuid.uuid4()

        with pytest.raises(SourceResolutionError) as exc_info:
            linker.resolve(source_loc, stored_text)

        assert "missing document_version_id" in exc_info.value.reason

    def test_resolve_error_contains_claim_id(
        self, linker: SourceLinker, document_version_id: str
    ):
        stored_text = "short"
        fact = ExtractedFact(
            field_name="test",
            value="X",
            confidence=1.0,
            source_span=SourceSpan(start_offset=0, end_offset=100),
        )
        source_loc = linker.attach(fact, document_version_id)
        claim_id = uuid.uuid4()
        loc_id = uuid.uuid4()
        source_loc.claim_id = claim_id
        source_loc.id = loc_id

        with pytest.raises(SourceResolutionError) as exc_info:
            linker.resolve(source_loc, stored_text)

        assert exc_info.value.claim_id == str(claim_id)
        assert exc_info.value.source_location_id == str(loc_id)


class TestSourceResolutionError:
    """Tests for SourceResolutionError exception."""

    def test_error_message_format(self):
        err = SourceResolutionError(
            claim_id="abc-123",
            source_location_id="loc-456",
            reason="offsets out of bounds",
        )
        assert "abc-123" in str(err)
        assert "offsets out of bounds" in str(err)

    def test_error_attributes(self):
        err = SourceResolutionError(
            claim_id="claim-1",
            source_location_id="loc-1",
            reason="test reason",
        )
        assert err.claim_id == "claim-1"
        assert err.source_location_id == "loc-1"
        assert err.reason == "test reason"


from decimal import Decimal
from unittest.mock import MagicMock, patch

from src.pipeline.source_linker import persist_fact


@pytest.fixture
def mock_session():
    """Create a mock SQLAlchemy session that assigns a UUID id on flush."""
    session = MagicMock()
    claim_id = uuid.uuid4()

    def side_effect_flush():
        # Simulate SQLAlchemy assigning an id after flush
        for call in session.add.call_args_list:
            obj = call[0][0]
            if hasattr(obj, "id") and obj.id is None:
                obj.id = claim_id

    session.flush.side_effect = side_effect_flush
    session._claim_id = claim_id  # store for test assertions
    return session


@pytest.fixture
def run_id() -> str:
    return str(uuid.uuid4())


class TestPersistFact:
    """Tests for persist_fact utility function."""

    def test_persist_fact_creates_claim_with_correct_claim_type(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        claim, _ = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert claim.claim_type == "loan_agreement.borrower_name"

    def test_persist_fact_creates_claim_with_correct_extracted_text(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        claim, _ = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert claim.extracted_text == "Rajesh Kumar"

    def test_persist_fact_creates_claim_with_correct_confidence(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        claim, _ = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert claim.confidence == Decimal("0.95")

    def test_persist_fact_creates_claim_with_correct_document_version_id(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        claim, _ = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert claim.document_version_id == uuid.UUID(document_version_id)

    def test_persist_fact_creates_claim_with_correct_run_id(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        claim, _ = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert claim.run_id == uuid.UUID(run_id)

    def test_persist_fact_creates_source_location_with_claim_id(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        claim, source_location = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert source_location.claim_id == mock_session._claim_id

    def test_persist_fact_creates_source_location_with_correct_offsets(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        _, source_location = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert source_location.start_offset == 10
        assert source_location.end_offset == 22

    def test_persist_fact_creates_source_location_with_page_number(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        _, source_location = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert source_location.page_number == 1

    def test_persist_fact_creates_source_location_with_section_id(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        _, source_location = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert source_location.section_id == "header"

    def test_persist_fact_creates_source_location_with_clause_ref(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        _, source_location = persist_fact(
            sample_fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert source_location.clause_ref == "loan_terms"

    def test_persist_fact_adds_claim_and_source_location_to_session(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        persist_fact(sample_fact, document_version_id, run_id, "loan_agreement", mock_session)
        assert mock_session.add.call_count == 2

    def test_persist_fact_flushes_session_after_claim(
        self, sample_fact: ExtractedFact, document_version_id: str, run_id: str, mock_session
    ):
        persist_fact(sample_fact, document_version_id, run_id, "loan_agreement", mock_session)
        mock_session.flush.assert_called_once()

    def test_persist_fact_repayment_row_claim_type(
        self, document_version_id: str, run_id: str, mock_session
    ):
        """Repayment row facts get claim_type like repayment_statement.row_1.amount_paid."""
        fact = ExtractedFact(
            field_name="amount_paid",
            value="5000.00",
            confidence=0.92,
            source_span=SourceSpan(start_offset=100, end_offset=107, page_number=2),
            fact_group_id="row_1",
        )
        claim, _ = persist_fact(
            fact, document_version_id, run_id, "repayment_statement", mock_session
        )
        assert claim.claim_type == "repayment_statement.row_1.amount_paid"

    def test_persist_fact_repayment_row_higher_index(
        self, document_version_id: str, run_id: str, mock_session
    ):
        """Row indexing works for multi-digit row numbers."""
        fact = ExtractedFact(
            field_name="outstanding_balance",
            value="45000.00",
            confidence=0.88,
            source_span=SourceSpan(start_offset=200, end_offset=210, page_number=3),
            fact_group_id="row_15",
        )
        claim, _ = persist_fact(
            fact, document_version_id, run_id, "repayment_statement", mock_session
        )
        assert claim.claim_type == "repayment_statement.row_15.outstanding_balance"

    def test_persist_fact_non_row_fact_group_id_uses_simple_claim_type(
        self, document_version_id: str, run_id: str, mock_session
    ):
        """Non-row fact_group_id values don't trigger row indexing."""
        fact = ExtractedFact(
            field_name="interest_rate",
            value="18.50",
            confidence=0.95,
            source_span=SourceSpan(start_offset=50, end_offset=55),
            fact_group_id="term_change_1",
        )
        claim, _ = persist_fact(
            fact, document_version_id, run_id, "modification_agreement", mock_session
        )
        assert claim.claim_type == "modification_agreement.interest_rate"

    def test_persist_fact_no_fact_group_id_uses_simple_claim_type(
        self, document_version_id: str, run_id: str, mock_session
    ):
        """None fact_group_id uses simple claim_type format."""
        fact = ExtractedFact(
            field_name="principal_amount",
            value="100000.00",
            confidence=0.99,
            source_span=SourceSpan(start_offset=30, end_offset=39),
            fact_group_id=None,
        )
        claim, _ = persist_fact(
            fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert claim.claim_type == "loan_agreement.principal_amount"

    def test_persist_fact_confidence_rounded_to_3_decimals(
        self, document_version_id: str, run_id: str, mock_session
    ):
        """Confidence is rounded to 3 decimal places."""
        fact = ExtractedFact(
            field_name="borrower_name",
            value="Test",
            confidence=0.95678,
            source_span=SourceSpan(start_offset=0, end_offset=4),
        )
        claim, _ = persist_fact(
            fact, document_version_id, run_id, "loan_agreement", mock_session
        )
        assert claim.confidence == Decimal("0.957")
