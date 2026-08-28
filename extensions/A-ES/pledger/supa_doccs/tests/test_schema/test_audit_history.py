# Feature: core-postgres-schema, Property 12: Audit Entity History Ordering
"""
Property-based test: Audit Entity History Ordering

For any entity identified by (entity_type, entity_id), querying audit_events
filtered by that pair and ordered by event_timestamp SHALL return all historical
state changes for that entity in chronological order.

Validates: Requirements 6.4
"""

import uuid
from datetime import datetime, timedelta, timezone

from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text


# Valid entity types as defined in the schema CHECK constraint
ENTITY_TYPES = (
    "document",
    "document_version",
    "claim",
    "source_location",
    "run",
    "run_step",
    "approval_queue",
    "decision",
)

ACTIONS = ("created", "updated", "status_changed", "deleted")

# Strategy: generate a list of explicit timestamps for audit events
# We use a base timestamp and generate offsets to create distinct timestamps
timestamp_offsets = st.lists(
    st.integers(min_value=0, max_value=100_000),  # seconds offset from base
    min_size=2,
    max_size=20,
    unique=True,  # ensure distinct timestamps
)


@given(
    entity_type=st.sampled_from(ENTITY_TYPES),
    offsets=timestamp_offsets,
)
def test_audit_entity_history_returns_chronological_order(db_session, entity_type, offsets):
    """
    **Validates: Requirements 6.4**

    Generate multiple audit_events for the same (entity_type, entity_id) with varying
    timestamps, insert them in shuffled order, and verify that querying with
    ORDER BY event_timestamp returns them in chronological order.
    """
    # Use a savepoint for this iteration
    savepoint = db_session.begin_nested()

    entity_id = uuid.uuid4()
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    # Build timestamps from offsets
    timestamps = [base_time + timedelta(seconds=offset) for offset in offsets]

    # Insert events in a shuffled order (reverse of sorted to guarantee out-of-order)
    shuffled_timestamps = list(reversed(sorted(timestamps)))

    for i, ts in enumerate(shuffled_timestamps):
        db_session.execute(
            text("""
                INSERT INTO audit_events (id, event_timestamp, entity_type, entity_id, action, actor_id, new_state)
                VALUES (:id, :event_timestamp, :entity_type, :entity_id, :action, :actor_id, :new_state)
            """),
            {
                "id": str(uuid.uuid4()),
                "event_timestamp": ts,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "action": "updated",
                "actor_id": f"test_actor_{i}",
                "new_state": "{}",
            },
        )
    db_session.flush()

    # Query using the entity history pattern from the design doc
    rows = db_session.execute(
        text("""
            SELECT * FROM audit_events
            WHERE entity_type = :entity_type AND entity_id = :entity_id
            ORDER BY event_timestamp
        """),
        {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
        },
    ).fetchall()

    # Verify: all inserted events are returned
    assert len(rows) == len(timestamps), (
        f"Expected {len(timestamps)} rows but got {len(rows)}"
    )

    # Verify: results are in chronological (ascending) order
    result_timestamps = [row.event_timestamp for row in rows]
    for i in range(len(result_timestamps) - 1):
        assert result_timestamps[i] <= result_timestamps[i + 1], (
            f"Results not in chronological order at index {i}: "
            f"{result_timestamps[i]} > {result_timestamps[i + 1]}"
        )

    # Verify: the sorted result matches the expected chronological order
    expected_sorted = sorted(timestamps)
    for i, (expected, actual) in enumerate(zip(expected_sorted, result_timestamps)):
        assert expected == actual, (
            f"Timestamp mismatch at position {i}: expected {expected}, got {actual}"
        )

    # Rollback this iteration so next one starts clean
    savepoint.rollback()
