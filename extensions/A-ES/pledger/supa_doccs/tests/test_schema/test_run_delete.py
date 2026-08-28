"""Delete-run must remove the full RESTRICT-FK dependency chain.

Regression: DELETE /runs/{id} failed with ForeignKeyViolation on
source_locations_claim_id_fkey for any run whose claims had source
locations or approval-queue entries (seen deleting run ee8f2b6d from
the UI). The chain decisions → approval_queue → claims ← source_locations
is all RESTRICT, so deletion must happen in dependency order.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from src.pipeline.run_cleanup import delete_run_and_dependents


def _insert_full_review_chain(session, sample_document_version):
    """Insert run + claim + source_location + approval_queue + decision."""
    run_id = uuid.uuid4()
    claim_id = uuid.uuid4()
    loc_id = uuid.uuid4()
    aq_id = uuid.uuid4()
    decision_id = uuid.uuid4()

    session.execute(
        text("""
            INSERT INTO runs (id, status, initiator, config_snapshot)
            VALUES (:id, 'completed', 'test', '{}')
        """),
        {"id": str(run_id)},
    )
    session.execute(
        text("""
            INSERT INTO claims (id, document_version_id, run_id,
                                extracted_text, claim_type, confidence)
            VALUES (:id, :dvid, :rid, 'text', 'factual', 0.9)
        """),
        {"id": str(claim_id), "dvid": str(sample_document_version), "rid": str(run_id)},
    )
    session.execute(
        text("""
            INSERT INTO source_locations (id, claim_id, document_version_id,
                                          start_offset, end_offset)
            VALUES (:id, :cid, :dvid, 0, 10)
        """),
        {"id": str(loc_id), "cid": str(claim_id), "dvid": str(sample_document_version)},
    )
    session.execute(
        text("""
            INSERT INTO approval_queue (id, claim_id, run_id, status, priority)
            VALUES (:id, :cid, :rid, 'pending', 3)
        """),
        {"id": str(aq_id), "cid": str(claim_id), "rid": str(run_id)},
    )
    # Guard trigger requires the decision to land while the entry is
    # still pending — insert it first, then transition to approved.
    session.execute(
        text("""
            INSERT INTO decisions (id, approval_queue_id, decision_value,
                                   reviewer_id, justification)
            VALUES (:id, :aqid, 'approved', 'tester', 'test justification')
        """),
        {"id": str(decision_id), "aqid": str(aq_id)},
    )
    session.execute(
        text("""
            UPDATE approval_queue SET status = 'approved' WHERE id = :id
        """),
        {"id": str(aq_id)},
    )
    session.flush()
    return run_id


def _count(session, table, run_id=None):
    if run_id is None:
        return session.execute(text(f"SELECT count(*) FROM {table}")).scalar()
    col = "id" if table == "runs" else "run_id"
    return session.execute(
        text(f"SELECT count(*) FROM {table} WHERE {col} = :rid"),
        {"rid": run_id},
    ).scalar()


def test_delete_run_removes_full_review_chain(
    db_session, sample_document_version
):
    run_id = _insert_full_review_chain(db_session, sample_document_version)

    # Pre-condition: the old delete order would fail here with
    # ForeignKeyViolation on source_locations_claim_id_fkey.
    assert _count(db_session, "claims", run_id) == 1

    delete_run_and_dependents(db_session, str(run_id))
    db_session.flush()

    assert _count(db_session, "runs", run_id) == 0
    assert _count(db_session, "run_steps", run_id) == 0
    assert _count(db_session, "claims", run_id) == 0
    assert _count(db_session, "approval_queue", run_id) == 0
    # source_locations and decisions referencing this run are gone
    assert (
        db_session.execute(
            text(
                """
                SELECT count(*) FROM source_locations
                WHERE claim_id NOT IN (SELECT id FROM claims)
                """
            )
        ).scalar()
        == 0
    )
    assert (
        db_session.execute(
            text(
                """
                SELECT count(*) FROM decisions
                WHERE approval_queue_id NOT IN (SELECT id FROM approval_queue)
                """
            )
        ).scalar()
        == 0
    )


def test_delete_run_with_no_dependents_succeeds(db_session):
    run_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO runs (id, status, initiator, config_snapshot)
            VALUES (:id, 'completed', 'test', '{}')
        """),
        {"id": str(run_id)},
    )
    db_session.flush()

    delete_run_and_dependents(db_session, str(run_id))
    db_session.flush()

    assert _count(db_session, "runs", run_id) == 0


def test_delete_run_with_unqueued_claim_only(
    db_session, sample_document_version
):
    """A claim with a source location but no queue entry also deletes."""
    run_id = uuid.uuid4()
    claim_id = uuid.uuid4()
    db_session.execute(
        text("""
            INSERT INTO runs (id, status, initiator, config_snapshot)
            VALUES (:id, 'completed', 'test', '{}')
        """),
        {"id": str(run_id)},
    )
    db_session.execute(
        text("""
            INSERT INTO claims (id, document_version_id, run_id,
                                extracted_text, claim_type, confidence)
            VALUES (:id, :dvid, :rid, 'text', 'factual', 0.9)
        """),
        {"id": str(claim_id), "dvid": str(sample_document_version), "rid": str(run_id)},
    )
    db_session.execute(
        text("""
            INSERT INTO source_locations (id, claim_id, document_version_id,
                                          start_offset, end_offset)
            VALUES (:id, :cid, :dvid, 5, 15)
        """),
        {"id": str(uuid.uuid4()), "cid": str(claim_id), "dvid": str(sample_document_version)},
    )
    db_session.flush()

    delete_run_and_dependents(db_session, str(run_id))
    db_session.flush()

    assert _count(db_session, "claims", run_id) == 0
