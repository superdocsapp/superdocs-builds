# Feature: core-postgres-schema, Property 9: One Decision Per Queue Entry
"""
Property 9: One Decision Per Queue Entry

For any approval_queue entry that already has a recorded decision, attempting to insert
a second decisions row referencing the same approval_queue_id SHALL raise a unique
constraint violation.

Validates: Requirements 5.5
"""

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, InternalError


@given(
    justification=st.text(min_size=1, max_size=200).filter(lambda s: "\x00" not in s),
)
def test_one_decision_per_queue_entry(db_session, sample_approval_queue_entry, justification):
    """**Validates: Requirements 5.5**

    Insert a first decision linked to the sample_approval_queue_entry, then attempt
    to insert a second decision with the same approval_queue_id. The second insert
    should raise a unique constraint violation (UNIQUE on approval_queue_id).
    """
    aq_id = sample_approval_queue_entry

    # Use a savepoint for this iteration
    savepoint = db_session.begin_nested()

    # Insert the first decision — should succeed
    first_decision_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO decisions (id, approval_queue_id, decision_value, reviewer_id, justification)
            VALUES (:id, :aq_id, 'approved', 'reviewer_1', :justification)
        """),
        {
            "id": str(first_decision_id),
            "aq_id": str(aq_id),
            "justification": justification,
        },
    )
    db_session.flush()

    # Attempt a second decision on the same approval_queue entry — should raise unique violation
    second_decision_id = uuid.uuid4()
    inner_savepoint = db_session.begin_nested()
    with pytest.raises((IntegrityError, InternalError)) as exc_info:
        db_session.execute(
            text("""
                INSERT INTO decisions (id, approval_queue_id, decision_value, reviewer_id, justification)
                VALUES (:id, :aq_id, 'rejected', 'reviewer_2', :justification)
            """),
            {
                "id": str(second_decision_id),
                "aq_id": str(aq_id),
                "justification": justification,
            },
        )
        db_session.flush()

    inner_savepoint.rollback()

    # Verify the error is a unique constraint violation
    error_msg = str(exc_info.value).lower()
    assert "unique" in error_msg or "duplicate" in error_msg, (
        f"Expected a unique constraint violation when inserting a second decision "
        f"for the same approval_queue_id, got: {exc_info.value}"
    )

    # Rollback the iteration
    savepoint.rollback()
