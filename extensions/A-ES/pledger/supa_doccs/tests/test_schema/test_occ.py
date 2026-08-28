# Feature: core-postgres-schema, Property 8: Optimistic Concurrency Control
"""
Property 8: Optimistic Concurrency Control

For any row in `runs`, `run_steps`, or `approval_queue` with a current version
value V, an UPDATE with WHERE version = V SHALL affect exactly one row and increment
version to V+1, while an UPDATE with WHERE version != V SHALL affect zero rows.

Validates: Requirements 4.5, 4.6
"""

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text


@given(wrong_version=st.integers(min_value=2, max_value=1000))
def test_optimistic_concurrency_control(db_session, sample_approval_queue_entry, wrong_version):
    """**Validates: Requirements 4.5, 4.6**

    1. Verify that an UPDATE with matching version (1) affects exactly 1 row
       and increments the version to 2.
    2. Verify that an UPDATE with a mismatching version affects 0 rows.
    """
    aq_id = sample_approval_queue_entry

    # Use a savepoint per iteration so version resets each time
    savepoint = db_session.begin_nested()

    # --- Step 1: Matching version update (version=1 → version should become 2) ---
    result = db_session.execute(
        text("""
            UPDATE approval_queue
            SET priority = 2, version = version + 1
            WHERE id = :id AND version = 1
        """),
        {"id": str(aq_id)},
    )
    assert result.rowcount == 1, (
        f"Expected 1 row affected for matching version update, got {result.rowcount}"
    )
    db_session.flush()

    # Verify version was incremented to 2
    row = db_session.execute(
        text("SELECT version, priority FROM approval_queue WHERE id = :id"),
        {"id": str(aq_id)},
    ).fetchone()
    assert row[0] == 2, f"Expected version=2 after update, got {row[0]}"
    assert row[1] == 2, f"Expected priority=2 after update, got {row[1]}"

    # --- Step 2: Mismatching version update (current is 2, use wrong_version != 2) ---
    # Ensure wrong_version != current version (2)
    if wrong_version == 2:
        wrong_version = 3

    result = db_session.execute(
        text("""
            UPDATE approval_queue
            SET priority = 4, version = version + 1
            WHERE id = :id AND version = :wrong_version
        """),
        {"id": str(aq_id), "wrong_version": wrong_version},
    )
    assert result.rowcount == 0, (
        f"Expected 0 rows affected for mismatching version (used version={wrong_version}, "
        f"current is 2), got {result.rowcount}"
    )

    # Verify row is unchanged (still version=2, priority=2)
    row = db_session.execute(
        text("SELECT version, priority FROM approval_queue WHERE id = :id"),
        {"id": str(aq_id)},
    ).fetchone()
    assert row[0] == 2, f"Expected version still 2 after failed OCC, got {row[0]}"
    assert row[1] == 2, f"Expected priority still 2 after failed OCC, got {row[1]}"

    # Rollback this iteration's changes so next one sees version=1 again
    savepoint.rollback()
