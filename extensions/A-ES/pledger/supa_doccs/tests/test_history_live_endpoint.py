"""Phase 5.2 rerun against the LIVE /runs/{id}/history endpoint.

The original tests/test_history_endpoint.py injected its own
InMemoryAuditStore into set_history_store() and drove changes through an
in-process engine — the endpoint never touched the audit_events table
and production had no store configured at all (503).

This test uses the real FastAPI app (lifespan included), so:
- GET /runs/{id}/history is served by SQLHistoryStore reading audit_events;
- the three state-changing events are written by the exact production
  writer functions used by the executor, the decision service, and the
  incremental flow.

Requires PostgreSQL with migrations applied (docdb).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from src.database import SessionLocal
from src.main import app
from src.pipeline.approval import ApprovalService
from src.pipeline.approval_postgres import PostgresApprovalStore
from src.pipeline.history_sql import (
    emit_incremental_update_event,
    emit_node_completed,
)


@pytest.fixture()
def live_client():
    """Real app with lifespan — history store wired to audit_events."""
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def run_id():
    return str(uuid.uuid4())


class TestHistoryEndpointLive:
    def test_history_store_is_wired_no_more_503(self, live_client):
        """GET /runs/{id}/history must not return 'History store not configured'."""
        resp = live_client.get(f"/runs/{uuid.uuid4()}/history")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["entries"] == []
        assert data["total"] == 0

    def test_three_sequential_changes_in_order_with_source_attribution(
        self, live_client, run_id
    ):
        doc_a = str(uuid.uuid4())  # source of change 1 (node completion)
        doc_b = None               # change 2 (decision) has no source doc
        doc_c = str(uuid.uuid4())  # source of change 3 (incremental update)

        # ---- Change 1: node completion (production executor writer) ----
        emit_node_completed(
            SessionLocal,
            run_id=run_id,
            node_name="extract_claims",
            node_status="completed",
            duration_ms=1234,
            source_ref=doc_a,
        )

        # ---- Change 2: approval decision via the LIVE REST endpoint ----
        approval_service = ApprovalService(PostgresApprovalStore(SessionLocal))
        item = approval_service.enqueue_item(
            run_id=run_id,
            item_type="finding",
            payload={"claim_text": "interest is 15% per annum"},
        )
        decide_resp = live_client.post(
            f"/approval/items/{item.id}/decide",
            json={
                "decision": "rejected",
                "reviewer_id": "live-reviewer",
                "justification": "Unsupported by source span",
            },
        )
        assert decide_resp.status_code == 200, decide_resp.text
        assert decide_resp.json()["success"] is True

        # ---- Change 3: incremental update (production incremental writer) --
        hashes_before = {"loan_agreement.rate": "a" * 64}
        hashes_after = {"loan_agreement.rate": "b" * 64}
        emit_incremental_update_event(
            SessionLocal,
            run_id=run_id,
            pile_id=str(uuid.uuid4()),
            new_document_id=doc_c,
            affected_sections=["loan_agreement.rate"],
            conflicts_detected=1,
            approval_items_created=1,
            hashes_before=hashes_before,
            hashes_after=hashes_after,
        )

        # ---- Read back through the LIVE endpoint ----
        resp = live_client.get(f"/runs/{run_id}/history")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["total"] == 3, f"expected 3 events, got {data}"
        entries = data["entries"]

        # Chronological order (oldest first)
        timestamps = [e["timestamp"] for e in entries]
        assert timestamps == sorted(timestamps)

        # Event 1: node completion, attributed to document A
        e1 = entries[0]
        assert e1["entity_type"] == "run"
        assert e1["action"] == "status_changed"
        assert e1["actor_id"] == "node:extract_claims"
        assert e1["source_document_id"] == doc_a
        assert e1["new_state"]["node"] == "extract_claims"

        # Event 2: decision, reviewer attributed, run-linked via new_state
        e2 = entries[1]
        assert e2["entity_type"] == "decision"
        assert e2["actor_id"] == "live-reviewer"
        assert e2["new_state"]["decision"] == "rejected"
        assert e2["new_state"]["justification"] == "Unsupported by source span"
        assert e2["new_state"]["run_id"] == run_id

        # Event 3: incremental update, attributed to document C
        e3 = entries[2]
        assert e3["entity_type"] == "run"
        assert e3["action"] == "updated"
        assert e3["source_document_id"] == doc_c
        assert e3["previous_state"]["section_hashes"] == hashes_before
        assert e3["new_state"]["affected_sections"] == ["loan_agreement.rate"]
        assert e3["new_state"]["conflicts_detected"] == 1

        # All three belong to THIS run only
        assert all(
            e["new_state"].get("run_id", run_id) == run_id for e in entries
        )
