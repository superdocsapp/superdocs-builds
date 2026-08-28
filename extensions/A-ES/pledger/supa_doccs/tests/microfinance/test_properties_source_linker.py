"""Property-based tests for source linker (Properties 13–16).

Feature: microfinance-ingestion-pipeline
Tests source pointer structural validity, resolution correctness,
round-trip property, and error reporting.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.pipeline.extractors.base import ExtractedFact, SourceSpan
from src.pipeline.source_linker import SourceLinker, SourceResolutionError
from src.models.claims import SourceLocation

from tests.microfinance.conftest import source_pointer_and_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DOC_VERSION_ID = "00000000-0000-0000-0000-000000000001"


def _make_fact_from_span(span: SourceSpan) -> ExtractedFact:
    """Create an ExtractedFact with the given source span."""
    return ExtractedFact(
        field_name="test_field",
        value="test_value",
        confidence=0.85,
        source_span=span,
        fact_group_id=None,
    )


# ---------------------------------------------------------------------------
# Property 13: Source Pointer Structural Validity
# ---------------------------------------------------------------------------


class TestProperty13SourcePointerStructuralValidity:
    """Property 13: Every attached source pointer has start_offset < end_offset
    and valid references.

    **Validates: Requirements 5.1, 5.2**
    """

    @given(data=source_pointer_and_text())
    @settings(max_examples=100)
    def test_attached_pointer_has_valid_offsets(
        self, data: tuple[SourceSpan, str]
    ):
        """Attached source pointers always have start_offset < end_offset."""
        span, text = data
        linker = SourceLinker()
        fact = _make_fact_from_span(span)

        source_location = linker.attach(fact, _DOC_VERSION_ID)

        # start_offset must be strictly less than end_offset
        assert source_location.start_offset < source_location.end_offset
        # document_version_id must be set
        assert source_location.document_version_id == uuid.UUID(_DOC_VERSION_ID)

    @given(data=source_pointer_and_text())
    @settings(max_examples=100)
    def test_attached_pointer_preserves_page_and_section(
        self, data: tuple[SourceSpan, str]
    ):
        """Attached source pointers preserve page_number and section_id from span."""
        span, text = data
        linker = SourceLinker()
        fact = _make_fact_from_span(span)

        source_location = linker.attach(fact, _DOC_VERSION_ID)

        assert source_location.page_number == span.page_number
        assert source_location.section_id == span.section_id

    def test_invalid_span_raises_value_error(self):
        """start_offset >= end_offset raises ValueError at attach time."""
        linker = SourceLinker()
        invalid_span = SourceSpan(start_offset=10, end_offset=5)
        fact = _make_fact_from_span(invalid_span)

        with pytest.raises(ValueError):
            linker.attach(fact, _DOC_VERSION_ID)

    def test_equal_offsets_raises_value_error(self):
        """start_offset == end_offset raises ValueError at attach time."""
        linker = SourceLinker()
        invalid_span = SourceSpan(start_offset=5, end_offset=5)
        fact = _make_fact_from_span(invalid_span)

        with pytest.raises(ValueError):
            linker.attach(fact, _DOC_VERSION_ID)


# ---------------------------------------------------------------------------
# Property 14: Source Pointer Resolution Correctness
# ---------------------------------------------------------------------------


class TestProperty14SourcePointerResolution:
    """Property 14: Resolve returns exactly text[start_offset:end_offset].

    **Validates: Requirements 5.3**
    """

    @given(data=source_pointer_and_text())
    @settings(max_examples=100)
    def test_resolve_returns_exact_substring(
        self, data: tuple[SourceSpan, str]
    ):
        """resolve() returns the exact substring text[start:end]."""
        span, text = data
        linker = SourceLinker()
        fact = _make_fact_from_span(span)

        source_location = linker.attach(fact, _DOC_VERSION_ID)
        resolved = linker.resolve(source_location, text)

        expected = text[span.start_offset:span.end_offset]
        assert resolved == expected

    @given(data=source_pointer_and_text())
    @settings(max_examples=100)
    def test_resolved_substring_is_non_empty(
        self, data: tuple[SourceSpan, str]
    ):
        """Resolved substring is always non-empty (since start < end)."""
        span, text = data
        linker = SourceLinker()
        fact = _make_fact_from_span(span)

        source_location = linker.attach(fact, _DOC_VERSION_ID)
        resolved = linker.resolve(source_location, text)

        assert len(resolved) > 0


# ---------------------------------------------------------------------------
# Property 15: Extraction Round-Trip
# ---------------------------------------------------------------------------


class TestProperty15ExtractionRoundTrip:
    """Property 15: Round-trip: resolve + re-parse yields same value.

    **Validates: Requirements 5.5**
    """

    @given(data=source_pointer_and_text())
    @settings(max_examples=100)
    def test_round_trip_resolution(
        self, data: tuple[SourceSpan, str]
    ):
        """Resolving a pointer produces the same substring that was originally spanned."""
        span, text = data
        linker = SourceLinker()

        # The "original extraction" value is the text at the span
        original_value = text[span.start_offset:span.end_offset]

        # Create a fact with that value
        fact = ExtractedFact(
            field_name="test_field",
            value=original_value,
            confidence=0.85,
            source_span=span,
            fact_group_id=None,
        )

        source_location = linker.attach(fact, _DOC_VERSION_ID)
        resolved = linker.resolve(source_location, text)

        # Round-trip: resolved text should equal the original value
        assert resolved == original_value


# ---------------------------------------------------------------------------
# Property 16: Source Resolution Error Reporting
# ---------------------------------------------------------------------------


class TestProperty16SourceResolutionError:
    """Property 16: Out-of-bounds -> SourceResolutionError with correct fields.

    **Validates: Requirements 5.6**
    """

    @given(
        text=st.text(min_size=5, max_size=50),
        extra_offset=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_end_offset_exceeds_text_length(self, text: str, extra_offset: int):
        """When end_offset exceeds text length, SourceResolutionError is raised."""
        assume(len(text) >= 5)
        linker = SourceLinker()

        # Create a source location with out-of-bounds end offset
        source_location = SourceLocation(
            document_version_id=uuid.UUID(_DOC_VERSION_ID),
            page_number=1,
            section_id=None,
            start_offset=0,
            end_offset=len(text) + extra_offset,
            clause_ref=None,
        )
        # Set identifiers for error reporting
        source_location.claim_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        source_location.id = uuid.UUID("00000000-0000-0000-0000-000000000088")

        with pytest.raises(SourceResolutionError) as exc_info:
            linker.resolve(source_location, text)

        error = exc_info.value
        assert error.claim_id == str(source_location.claim_id)
        assert error.source_location_id == str(source_location.id)
        assert "exceed" in error.reason.lower() or "out" in error.reason.lower()

    @given(
        text=st.text(min_size=5, max_size=50),
    )
    @settings(max_examples=100)
    def test_missing_document_version_id(self, text: str):
        """When document_version_id is None, SourceResolutionError is raised."""
        assume(len(text) >= 5)
        linker = SourceLinker()

        source_location = SourceLocation(
            document_version_id=None,
            page_number=1,
            section_id=None,
            start_offset=0,
            end_offset=2,
            clause_ref=None,
        )
        source_location.claim_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        source_location.id = uuid.UUID("00000000-0000-0000-0000-000000000088")

        with pytest.raises(SourceResolutionError) as exc_info:
            linker.resolve(source_location, text)

        error = exc_info.value
        assert "document_version_id" in error.reason.lower() or "missing" in error.reason.lower()

    @given(
        text_len=st.integers(min_value=5, max_value=50),
        start_beyond=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_start_offset_exceeds_text_length(self, text_len: int, start_beyond: int):
        """When start_offset exceeds text length, SourceResolutionError is raised."""
        text = "a" * text_len
        linker = SourceLinker()

        source_location = SourceLocation(
            document_version_id=uuid.UUID(_DOC_VERSION_ID),
            page_number=1,
            section_id=None,
            start_offset=text_len + start_beyond,
            end_offset=text_len + start_beyond + 1,
            clause_ref=None,
        )
        source_location.claim_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        source_location.id = uuid.UUID("00000000-0000-0000-0000-000000000088")

        with pytest.raises(SourceResolutionError) as exc_info:
            linker.resolve(source_location, text)

        error = exc_info.value
        assert error.claim_id is not None
        assert error.source_location_id is not None
