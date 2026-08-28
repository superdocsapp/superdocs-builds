# Feature: core-postgres-schema, Property 10: Decision Guard on Pending Status
"""
Property 10: Decision Guard on Pending Status

For any approval_queue entry whose status is NOT 'pending' (i.e., 'approved' or 'rejected'),
attempting to insert a decisions row referencing that entry SHALL be rejected by the guard trigger.

Validates: Requirements 5.7
"""

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import InternalError


@given(non_pending_status=st.sampled_from(["approved", "rejected"]))
def test_decision_guard_on_pending_status(db_session, sample_claim, non_pending_status):
    """**Validates: Requirements 5.7**

    Generate approval_queue entries with non-pending statuses and verify that
    inserting a decision referencing that entry is rejected by the
    guard_decision_on_pending trigger.
    """
    # Use a savepoint for this iteration
    savepoint = db_session.begin_nested()

    # Create an approval_queue entry directly with a non-pending status
    aq_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO approval_queue (id, claim_id, status, priority)
            VALUES (:id, :claim_id, :status, :priority)
        """),
        {
            "id": str(aq_id),
            "claim_id": str(sample_claim),
            "status": non_pending_status,
            "priority": 3,
        },
    )
    db_session.flush()

    # Attempt to insert a decision against this non-pending queue entry
    decision_id = uuid.uuid4()
    inner_savepoint = db_session.begin_nested()
    with pytest.raises((InternalError, Exception)) as exc_info:
        db_session.execute(
            text("""
                INSERT INTO decisions (id, approval_queue_id, decision_value, reviewer_id, justification)
                VALUES (:id, :aq_id, :decision_value, :reviewer_id, :justification)
            """),
            {
                "id": str(decision_id),
                "aq_id": str(aq_id),
                "decision_value": "approved",
                "reviewer_id": "test_reviewer",
                "justification": "Test justification for guard trigger validation",
            },
        )
        db_session.flush()

    inner_savepoint.rollback()

    # Verify the error message mentions the guard trigger rejection
    assert "Cannot record decision" in str(exc_info.value), (
        f"Expected 'Cannot record decision' in error for decision insert "
        f"against '{non_pending_status}' queue entry, got: {exc_info.value}"
    )

    # Rollback this iteration
    savepoint.rollback()
