# Feature: core-postgres-schema, Property 6: Resume Query Correctness
"""
Property-based test: Resume Query Correctness

For any run with an arbitrary sequence of steps in various statuses, querying
run_steps WHERE run_id = :id AND status = 'completed' ORDER BY step_order DESC LIMIT 1
SHALL return the step with the highest step_order among all completed steps for that run,
or no rows if none are completed.

Validates: Requirements 3.3
"""

import uuid

from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text


# Strategy: generate a list of (step_order, status) tuples with unique step_orders
STEP_STATUSES = ("pending", "running", "completed", "failed", "skipped")

step_entries = st.lists(
    st.tuples(
        st.integers(min_value=1, max_value=10000),
        st.sampled_from(STEP_STATUSES),
    ),
    min_size=1,
    max_size=30,
    unique_by=lambda x: x[0],  # unique step_order values
)


@given(steps=step_entries)
def test_resume_query_returns_highest_completed_step(db_session, sample_run, steps):
    """
    **Validates: Requirements 3.3**

    Generate arbitrary sequences of run_steps with mixed statuses and verify the
    resume query returns the highest completed step_order, or no rows if none completed.
    """
    run_id = sample_run

    # Use a savepoint for each iteration's data so it doesn't accumulate
    savepoint = db_session.begin_nested()

    # Insert all run_steps for the sample_run
    for step_order, status in steps:
        db_session.execute(
            text("""
                INSERT INTO run_steps (id, run_id, step_name, step_order, status)
                VALUES (:id, :run_id, :step_name, :step_order, :status)
            """),
            {
                "id": str(uuid.uuid4()),
                "run_id": str(run_id),
                "step_name": f"step_{step_order}",
                "step_order": step_order,
                "status": status,
            },
        )
    db_session.flush()

    # Execute the resume query
    result = db_session.execute(
        text("""
            SELECT * FROM run_steps
            WHERE run_id = :run_id AND status = 'completed'
            ORDER BY step_order DESC
            LIMIT 1
        """),
        {"run_id": str(run_id)},
    ).fetchone()

    # Determine expected result
    completed_steps = [order for order, status in steps if status == "completed"]

    if not completed_steps:
        # No completed steps — query should return no rows
        assert result is None, (
            f"Expected no rows (no completed steps) but got step_order={result.step_order}"
        )
    else:
        # Should return the step with the maximum step_order among completed steps
        expected_max_order = max(completed_steps)
        assert result is not None, (
            f"Expected a row with step_order={expected_max_order} but got None"
        )
        assert result.step_order == expected_max_order, (
            f"Expected step_order={expected_max_order} but got step_order={result.step_order}"
        )
        assert result.status == "completed", (
            f"Expected status='completed' but got status='{result.status}'"
        )

    # Rollback this iteration's inserts so next iteration starts clean
    savepoint.rollback()
