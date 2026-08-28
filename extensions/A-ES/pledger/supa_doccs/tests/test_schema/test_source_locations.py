# Feature: core-postgres-schema, Property 5: Source Location Offset Ordering
"""
Property-based test: Source Location Offset Ordering

For any pair of integers (start_offset, end_offset), insertion into source_locations
SHALL succeed only when start_offset < end_offset, and SHALL be rejected otherwise.

**Validates: Requirements 2.5**
"""

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@given(
    start_offset=st.integers(min_value=0, max_value=10_000),
    end_offset=st.integers(min_value=0, max_value=10_000),
)
def test_source_location_offset_ordering(
    start_offset: int,
    end_offset: int,
    db_session,
    sample_claim,
    sample_document_version,
):
    """Insertion into source_locations succeeds iff start_offset < end_offset.

    **Validates: Requirements 2.5**
    """
    loc_id = uuid.uuid4()

    # Use a savepoint so that constraint violations don't poison the session
    savepoint = db_session.begin_nested()
    try:
        db_session.execute(
            text("""
                INSERT INTO source_locations (id, claim_id, document_version_id, start_offset, end_offset)
                VALUES (:id, :claim_id, :document_version_id, :start_offset, :end_offset)
            """),
            {
                "id": str(loc_id),
                "claim_id": str(sample_claim),
                "document_version_id": str(sample_document_version),
                "start_offset": start_offset,
                "end_offset": end_offset,
            },
        )
        db_session.flush()
        savepoint.commit()

        # If we got here, insertion succeeded — start must be less than end
        assert start_offset < end_offset, (
            f"Insertion should have failed for start_offset={start_offset} >= end_offset={end_offset}"
        )

    except IntegrityError:
        savepoint.rollback()

        # If insertion was rejected, start must be >= end (CHECK constraint violated)
        assert start_offset >= end_offset, (
            f"Insertion should have succeeded for start_offset={start_offset} < end_offset={end_offset}"
        )
