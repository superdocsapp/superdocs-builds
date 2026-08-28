# Feature: core-postgres-schema, Property 11: Audit Events Append-Only
"""
Property 11: Audit Events Append-Only

For any existing row in the `audit_events` table, any UPDATE or DELETE operation
SHALL be rejected by the immutability trigger unconditionally.

Validates: Requirements 6.2
"""

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import InternalError


# Valid entity types for the audit_events table
ENTITY_TYPES = [
    "document",
    "document_version",
    "claim",
    "source_location",
    "run",
    "run_step",
    "approval_queue",
    "decision",
]

# Valid action values for the audit_events table
ACTIONS = ["created", "updated", "status_changed", "deleted"]


def _insert_audit_event(
    db_session, entity_type: str, action: str
) -> uuid.UUID:
    """Insert an audit_event row with the given entity_type and action."""
    event_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO audit_events (id, entity_type, entity_id, action, actor_id, new_state)
            VALUES (:id, :entity_type, :entity_id, :action, :actor_id, :new_state)
        """),
        {
            "id": str(event_id),
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "action": action,
            "actor_id": "test_property_11",
            "new_state": "{}",
        },
    )
    db_session.flush()
    return event_id


@given(
    entity_type=st.sampled_from(ENTITY_TYPES),
    action=st.sampled_from(ACTIONS),
)
def test_audit_events_reject_update(db_session, entity_type, action):
    """**Validates: Requirements 6.2**

    Insert an audit_event row, then attempt an UPDATE. The prevent_audit_mutation
    trigger must reject the operation unconditionally.
    """
    savepoint = db_session.begin_nested()
    event_id = _insert_audit_event(db_session, entity_type, action)

    inner_savepoint = db_session.begin_nested()
    with pytest.raises((InternalError, Exception)) as exc_info:
        db_session.execute(
            text("""
                UPDATE audit_events SET actor_id = 'hacker' WHERE id = :id
            """),
            {"id": str(event_id)},
        )
        db_session.flush()

    inner_savepoint.rollback()

    assert "append-only" in str(exc_info.value).lower(), (
        f"Expected 'append-only' in error for UPDATE on audit_events "
        f"(entity_type={entity_type}, action={action}), got: {exc_info.value}"
    )

    savepoint.rollback()


@given(
    entity_type=st.sampled_from(ENTITY_TYPES),
    action=st.sampled_from(ACTIONS),
)
def test_audit_events_reject_delete(db_session, entity_type, action):
    """**Validates: Requirements 6.2**

    Insert an audit_event row, then attempt a DELETE. The prevent_audit_mutation
    trigger must reject the operation unconditionally.
    """
    savepoint = db_session.begin_nested()
    event_id = _insert_audit_event(db_session, entity_type, action)

    inner_savepoint = db_session.begin_nested()
    with pytest.raises((InternalError, Exception)) as exc_info:
        db_session.execute(
            text("DELETE FROM audit_events WHERE id = :id"),
            {"id": str(event_id)},
        )
        db_session.flush()

    inner_savepoint.rollback()

    assert "append-only" in str(exc_info.value).lower(), (
        f"Expected 'append-only' in error for DELETE on audit_events "
        f"(entity_type={entity_type}, action={action}), got: {exc_info.value}"
    )

    savepoint.rollback()
