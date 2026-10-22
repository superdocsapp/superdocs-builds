"""
Genuinely live version of the Phase 3 DB-wipe resilience test. Guarded the
same way Task 1's DOCTASK_LIVE_MODEL_CALLS was — set REDLINER_LIVE_CALLS=1
to run it (see CLAUDE.md). Not run by default; costs real SuperDocs
operations (one negotiation: 1 document + 2 attachment uploads, one round,
one batch of decisions, one get_session_jobs call).

This is the one place tracker_service._rebuild_from_job_history's
live-confirmed assumptions (get_session_jobs shape, result.document_changes
.changes for decided items) get checked against the real API, not just a
respx mock built from a snapshot. The AI's HITL behavior isn't fully
deterministic (observed live 2026-08-12: a round sometimes completes with
zero pending changes instead of flagging any for approval) — the test
handles both outcomes rather than assuming a round always proposes
something.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import OpenItem
from app.services import negotiation_service, round_service, tracker_service
from app.superdocs_client import SuperDocsClient

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"

pytestmark = pytest.mark.skipif(
    os.environ.get("REDLINER_LIVE_CALLS") != "1",
    reason="live SuperDocs call — set REDLINER_LIVE_CALLS=1 to run",
)


@pytest.mark.live
def test_reconcile_rebuilds_from_real_job_history_after_local_wipe():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    client = SuperDocsClient()  # real key from .env

    negotiation = negotiation_service.start_negotiation(
        db,
        client,
        "Live resilience check",
        (SEED / "cba-draft.txt").read_bytes(),
        (SEED / "union-position.txt").read_bytes(),
        (SEED / "employer-position.txt").read_bytes(),
    )

    round_ = round_service.start_round(db, client, negotiation.id)
    # the AI isn't fully deterministic despite approval_mode=ask_every_time
    # — observed live 2026-08-12, a round sometimes completes with zero
    # pending changes instead of flagging anything for HITL review. Both
    # outcomes are legitimate; the test proves reconcile() handles either
    # without crashing, rather than assuming a round always has something
    # to decide.
    changes = round_service.list_pending_changes(db, client, round_.id) if round_.status == "awaiting_approval" else []

    if changes:
        decisions = [{"chunk_id": c["chunk_id"], "approved": True} for c in changes]
        round_ = round_service.decide(db, client, round_.id, decisions)
        assert round_.status == "completed", f"round didn't complete after deciding all changes: {round_.status}"

    proposed_count = db.query(OpenItem).filter_by(negotiation_id=negotiation.id).count()
    assert proposed_count == len(changes)

    # simulate DB loss: wipe OpenItem rows only, Negotiation/Round rows survive
    db.query(OpenItem).delete()
    db.commit()
    assert db.query(OpenItem).filter_by(negotiation_id=negotiation.id).count() == 0

    reconciled = tracker_service.reconcile(db, client, negotiation.id)

    assert len(reconciled) == proposed_count, "rebuild from real job history didn't crash, but recovered wrong count"
    if changes:
        # decisions were made — this exercises the real
        # result.document_changes.changes rebuild path
        for row in reconciled:
            assert row["status"] == "approved", row
    else:
        assert reconciled == []

    # idempotent: second call hits the fast local-rows path, no duplicates
    again = tracker_service.reconcile(db, client, negotiation.id)
    assert again == reconciled
    assert db.query(OpenItem).filter_by(negotiation_id=negotiation.id).count() == proposed_count
