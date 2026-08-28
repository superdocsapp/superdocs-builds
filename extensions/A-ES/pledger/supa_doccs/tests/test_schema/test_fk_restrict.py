# Feature: core-postgres-schema, Property 13: ON DELETE RESTRICT Enforcement
"""
Property-based test: ON DELETE RESTRICT Enforcement

For any parent record in documents, document_versions, claims, runs, or approval_queue
that has at least one child row referencing it, a DELETE on the parent SHALL be rejected
with a foreign key violation.

**Validates: Requirements 7.2**
"""

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


# Define the parent-child relationships to test
PARENT_CHILD_RELATIONSHIPS = [
    "documents_with_versions",
    "document_versions_with_claims",
    "runs_with_claims",
    "claims_with_source_locations",
    "claims_with_approval_queue",
]


@given(
    relationship=st.sampled_from(PARENT_CHILD_RELATIONSHIPS),
)
def test_on_delete_restrict_enforcement(
    relationship: str,
    db_session,
    sample_document,
    sample_document_version,
    sample_run,
    sample_claim,
    sample_approval_queue_entry,
):
    """Deleting a parent record with existing children raises IntegrityError.

    **Validates: Requirements 7.2**
    """
    if relationship == "documents_with_versions":
        # sample_document has sample_document_version as a child
        inner_savepoint = db_session.begin_nested()
        with pytest.raises(IntegrityError):
            db_session.execute(
                text("DELETE FROM documents WHERE id = :id"),
                {"id": str(sample_document)},
            )
            db_session.flush()
        inner_savepoint.rollback()

    elif relationship == "document_versions_with_claims":
        # sample_document_version has sample_claim as a child
        inner_savepoint = db_session.begin_nested()
        with pytest.raises(IntegrityError):
            db_session.execute(
                text("DELETE FROM document_versions WHERE id = :id"),
                {"id": str(sample_document_version)},
            )
            db_session.flush()
        inner_savepoint.rollback()

    elif relationship == "runs_with_claims":
        # sample_run has sample_claim as a child
        inner_savepoint = db_session.begin_nested()
        with pytest.raises(IntegrityError):
            db_session.execute(
                text("DELETE FROM runs WHERE id = :id"),
                {"id": str(sample_run)},
            )
            db_session.flush()
        inner_savepoint.rollback()

    elif relationship == "claims_with_source_locations":
        # Insert a source_location child for sample_claim, then try to delete the claim
        sl_id = uuid.uuid4()
        db_session.execute(
            text("""
                INSERT INTO source_locations (id, claim_id, document_version_id, start_offset, end_offset)
                VALUES (:id, :claim_id, :dv_id, :start, :end)
            """),
            {
                "id": str(sl_id),
                "claim_id": str(sample_claim),
                "dv_id": str(sample_document_version),
                "start": 0,
                "end": 10,
            },
        )
        db_session.flush()

        inner_savepoint = db_session.begin_nested()
        with pytest.raises(IntegrityError):
            db_session.execute(
                text("DELETE FROM claims WHERE id = :id"),
                {"id": str(sample_claim)},
            )
            db_session.flush()
        inner_savepoint.rollback()

    elif relationship == "claims_with_approval_queue":
        # sample_claim has sample_approval_queue_entry as a child
        # Try to delete the claim (which is referenced by approval_queue)
        inner_savepoint = db_session.begin_nested()
        with pytest.raises(IntegrityError):
            db_session.execute(
                text("DELETE FROM claims WHERE id = :id"),
                {"id": str(sample_claim)},
            )
            db_session.flush()
        inner_savepoint.rollback()
