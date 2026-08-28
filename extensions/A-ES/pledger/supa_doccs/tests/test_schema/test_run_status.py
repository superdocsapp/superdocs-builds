# Feature: core-postgres-schema, Property 7: Run Status State Machine
"""
Property 7: Run Status State Machine

For any run with a current status, a status UPDATE SHALL succeed only if the transition
is valid according to the state machine (pending → running, running → completed|failed|cancelled),
and SHALL be rejected for all other transitions including backward transitions.

Validates: Requirements 3.4
"""

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import InternalError


# All valid run statuses
ALL_STATUSES = ["pending", "running", "completed", "failed", "cancelled"]

# Valid transitions as defined by the state machine trigger
VALID_TRANSITIONS = {
    ("pending", "running"),
    ("running", "completed"),
    ("running", "failed"),
    ("running", "cancelled"),
}


def _create_run_with_status(db_session, target_status: str) -> uuid.UUID:
    """Create a run and transition it to the target status.

    Runs are created with default 'pending' status. To reach 'running',
    we first do a valid pending→running transition. Terminal states
    (completed, failed, cancelled) require pending→running→terminal.
    """
    run_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO runs (id, status, initiator, config_snapshot)
            VALUES (:id, 'pending', :initiator, '{}')
        """),
        {"id": str(run_id), "initiator": "test_state_machine"},
    )
    db_session.flush()

    if target_status == "pending":
        return run_id

    # Transition to running
    db_session.execute(
        text("UPDATE runs SET status = 'running' WHERE id = :id"),
        {"id": str(run_id)},
    )
    db_session.flush()

    if target_status == "running":
        return run_id

    # Transition to terminal state (completed, failed, cancelled)
    db_session.execute(
        text("UPDATE runs SET status = :status WHERE id = :id"),
        {"id": str(run_id), "status": target_status},
    )
    db_session.flush()

    return run_id


@given(
    current_status=st.sampled_from(ALL_STATUSES),
    new_status=st.sampled_from(ALL_STATUSES),
)
def test_run_status_state_machine(db_session, current_status, new_status):
    """**Validates: Requirements 3.4**

    Generate all pairs of (current_status, new_status) and verify only valid
    transitions succeed. Invalid transitions must raise an exception from the
    trigger.
    """
    # Skip no-op transitions (same status) — the trigger allows these through
    if current_status == new_status:
        return

    # Use a savepoint for this iteration
    savepoint = db_session.begin_nested()

    # Create a run already at `current_status`
    run_id = _create_run_with_status(db_session, current_status)

    transition = (current_status, new_status)

    if transition in VALID_TRANSITIONS:
        # Valid transition: should succeed
        db_session.execute(
            text("UPDATE runs SET status = :new_status WHERE id = :id"),
            {"id": str(run_id), "new_status": new_status},
        )
        db_session.flush()

        # Verify the status was updated
        result = db_session.execute(
            text("SELECT status FROM runs WHERE id = :id"),
            {"id": str(run_id)},
        )
        row = result.fetchone()
        assert row[0] == new_status, (
            f"Expected status '{new_status}' after valid transition "
            f"'{current_status}' → '{new_status}', got '{row[0]}'"
        )
    else:
        # Invalid transition: should raise an exception
        with pytest.raises((InternalError, Exception)) as exc_info:
            db_session.execute(
                text("UPDATE runs SET status = :new_status WHERE id = :id"),
                {"id": str(run_id), "new_status": new_status},
            )
            db_session.flush()

        # Verify the error message mentions invalid transition
        assert "Invalid run status transition" in str(exc_info.value), (
            f"Expected 'Invalid run status transition' in error for "
            f"'{current_status}' → '{new_status}', got: {exc_info.value}"
        )

    # Rollback this iteration so next one starts fresh
    savepoint.rollback()
