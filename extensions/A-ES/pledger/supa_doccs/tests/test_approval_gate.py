"""Approval gate tests: programmatic approve/reject via REST endpoint.

Validates invariant 5 in docs/invariants.md:
- Approving or rejecting one item never discards the rest of the queue.
- Rejecting item X has zero effect on approved item Y's committed state.
- The gate is drivable programmatically (REST endpoint), not only UI.

No live LLM key or Postgres required — uses in-memory store.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.pipeline.approval import (
    ApprovalService,
    DecisionValue,
    InMemoryApprovalStore,
    ItemAlreadyDecidedError,
    ItemNotFoundError,
    ItemStatus,
    QueueItem,
)
from src.pipeline.approval_api import (
    router,
    set_approval_service,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    """Fresh in-memory approval store."""
    return InMemoryApprovalStore()


@pytest.fixture
def service(store):
    """ApprovalService backed by in-memory store."""
    return ApprovalService(store)


@pytest.fixture
def client(service):
    """FastAPI TestClient with approval router configured."""
    set_approval_service(service)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    set_approval_service(None)


@pytest.fixture
def seeded_queue(service):
    """Seed a queue with 3 pending items for the same run_id."""
    run_id = str(uuid.uuid4())
    items = []
    for i in range(3):
        item = service.enqueue_item(
            run_id=run_id,
            item_type="finding",
            payload={
                "claim_text": f"Claim number {i}",
                "confidence": 0.8 - (i * 0.1),
                "rule_id": f"RULE-{i:03d}",
            },
        )
        items.append(item)
    return run_id, items


# ---------------------------------------------------------------------------
# Service-level tests (unit tests without HTTP)
# ---------------------------------------------------------------------------


class TestApprovalServiceUnit:
    """Unit tests for the ApprovalService layer."""

    def test_enqueue_creates_pending_item(self, service):
        """Enqueueing creates an item with pending status."""
        run_id = str(uuid.uuid4())
        item = service.enqueue_item(
            run_id=run_id,
            item_type="conflict",
            payload={"description": "Version conflict"},
        )

        assert item.status == ItemStatus.PENDING
        assert item.run_id == run_id
        assert item.item_type == "conflict"
        assert item.decision is None

    def test_approve_transitions_to_approved(self, service, seeded_queue):
        """Approving an item changes its status to 'approved'."""
        run_id, items = seeded_queue
        item_to_approve = items[0]

        result = service.decide(
            item_id=item_to_approve.id,
            decision=DecisionValue.APPROVED,
            reviewer_id="reviewer-1",
            justification="Claim is valid and well-sourced",
        )

        assert result.success
        assert result.decision == DecisionValue.APPROVED

        # Verify the item's state changed
        updated = service.get_item(item_to_approve.id)
        assert updated.status == ItemStatus.APPROVED
        assert updated.reviewer_id == "reviewer-1"
        assert updated.decided_at is not None

    def test_reject_transitions_to_rejected(self, service, seeded_queue):
        """Rejecting an item changes its status to 'rejected'."""
        run_id, items = seeded_queue
        item_to_reject = items[1]

        result = service.decide(
            item_id=item_to_reject.id,
            decision=DecisionValue.REJECTED,
            reviewer_id="reviewer-2",
            justification="Claim is unsupported by evidence",
        )

        assert result.success
        assert result.decision == DecisionValue.REJECTED

        updated = service.get_item(item_to_reject.id)
        assert updated.status == ItemStatus.REJECTED

    def test_reject_does_not_affect_other_items(self, service, seeded_queue):
        """INVARIANT: Rejecting one item has zero effect on others."""
        run_id, items = seeded_queue
        item_to_reject = items[0]
        other_items = items[1:]

        # Snapshot other items' state before the rejection
        before_states = {
            i.id: (i.status, i.decision, i.payload.copy())
            for i in other_items
        }

        # Reject item 0
        service.decide(
            item_id=item_to_reject.id,
            decision=DecisionValue.REJECTED,
            reviewer_id="reviewer-1",
            justification="Not relevant",
        )

        # Verify other items are completely unchanged
        for item in other_items:
            refreshed = service.get_item(item.id)
            before_status, before_decision, before_payload = before_states[item.id]
            assert refreshed.status == before_status, (
                f"Item {item.id} status changed from {before_status} "
                f"to {refreshed.status} after rejecting a different item"
            )
            assert refreshed.decision == before_decision
            assert refreshed.payload == before_payload

    def test_approve_does_not_affect_other_items(self, service, seeded_queue):
        """INVARIANT: Approving one item has zero effect on others."""
        run_id, items = seeded_queue
        item_to_approve = items[2]
        other_items = items[:2]

        before_states = {
            i.id: (i.status, i.decision) for i in other_items
        }

        service.decide(
            item_id=item_to_approve.id,
            decision=DecisionValue.APPROVED,
            reviewer_id="reviewer-1",
            justification="Valid claim",
        )

        for item in other_items:
            refreshed = service.get_item(item.id)
            assert refreshed.status == before_states[item.id][0]
            assert refreshed.decision == before_states[item.id][1]

    def test_cannot_decide_already_decided_item(self, service, seeded_queue):
        """Deciding an already-decided item returns failure."""
        run_id, items = seeded_queue
        item = items[0]

        # First decision succeeds
        service.decide(
            item_id=item.id,
            decision=DecisionValue.APPROVED,
            reviewer_id="r1",
            justification="ok",
        )

        # Second decision fails
        result = service.decide(
            item_id=item.id,
            decision=DecisionValue.REJECTED,
            reviewer_id="r2",
            justification="changed my mind",
        )

        assert not result.success
        assert "already" in result.error.lower()

        # Item remains approved (first decision wins)
        refreshed = service.get_item(item.id)
        assert refreshed.status == ItemStatus.APPROVED
        assert refreshed.reviewer_id == "r1"

    def test_pending_count_decreases_after_decision(self, service, seeded_queue):
        """The pending count decreases as items are decided."""
        run_id, items = seeded_queue

        pending = service.get_pending(run_id)
        assert len(pending) == 3

        service.decide(
            item_id=items[0].id,
            decision=DecisionValue.APPROVED,
            reviewer_id="r1",
            justification="ok",
        )

        pending = service.get_pending(run_id)
        assert len(pending) == 2

    def test_decide_nonexistent_item_returns_failure(self, service):
        """Deciding a nonexistent item returns a failure result."""
        result = service.decide(
            item_id="nonexistent-id",
            decision=DecisionValue.APPROVED,
            reviewer_id="r1",
            justification="test",
        )

        assert not result.success
        assert "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# REST endpoint tests (the callable operation requirement)
# ---------------------------------------------------------------------------


class TestApprovalEndpoint:
    """Tests for the REST approve/reject endpoint."""

    def test_approve_via_rest(self, client, seeded_queue):
        """POST /approval/items/{id}/decide with 'approved' works."""
        run_id, items = seeded_queue

        response = client.post(
            f"/approval/items/{items[0].id}/decide",
            json={
                "decision": "approved",
                "reviewer_id": "api-bot",
                "justification": "Automated approval — meets criteria",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["decision"] == "approved"
        assert data["item_id"] == items[0].id

    def test_reject_via_rest(self, client, seeded_queue):
        """POST /approval/items/{id}/decide with 'rejected' works."""
        run_id, items = seeded_queue

        response = client.post(
            f"/approval/items/{items[1].id}/decide",
            json={
                "decision": "rejected",
                "reviewer_id": "api-bot",
                "justification": "Insufficient evidence",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["decision"] == "rejected"

    def test_approve_one_reject_another_same_batch_independence(
        self, client, seeded_queue
    ):
        """CRITICAL TEST: Approve item A, reject item B in same batch.

        Assert the rejected item had zero effect on the approved item's
        committed state.
        """
        run_id, items = seeded_queue
        item_to_approve = items[0]
        item_to_reject = items[1]
        item_untouched = items[2]

        # Approve item 0
        resp_approve = client.post(
            f"/approval/items/{item_to_approve.id}/decide",
            json={
                "decision": "approved",
                "reviewer_id": "bot-alpha",
                "justification": "Claim verified against source",
            },
        )
        assert resp_approve.status_code == 200

        # Reject item 1
        resp_reject = client.post(
            f"/approval/items/{item_to_reject.id}/decide",
            json={
                "decision": "rejected",
                "reviewer_id": "bot-beta",
                "justification": "Claim contradicts known data",
            },
        )
        assert resp_reject.status_code == 200

        # Now verify independence:

        # 1. Approved item retains its committed state unchanged by the rejection
        resp_get_approved = client.get(
            f"/approval/items/{item_to_approve.id}"
        )
        assert resp_get_approved.status_code == 200
        approved_data = resp_get_approved.json()
        assert approved_data["status"] == "approved"
        assert approved_data["reviewer_id"] == "bot-alpha"
        assert approved_data["justification"] == "Claim verified against source"
        assert approved_data["payload"]["claim_text"] == "Claim number 0"

        # 2. Rejected item has its own independent state
        resp_get_rejected = client.get(
            f"/approval/items/{item_to_reject.id}"
        )
        assert resp_get_rejected.status_code == 200
        rejected_data = resp_get_rejected.json()
        assert rejected_data["status"] == "rejected"
        assert rejected_data["reviewer_id"] == "bot-beta"
        assert rejected_data["justification"] == "Claim contradicts known data"

        # 3. Untouched item remains pending (not affected by either decision)
        resp_get_untouched = client.get(
            f"/approval/items/{item_untouched.id}"
        )
        assert resp_get_untouched.status_code == 200
        untouched_data = resp_get_untouched.json()
        assert untouched_data["status"] == "pending"
        assert untouched_data["decision"] is None
        assert untouched_data["reviewer_id"] is None

        # 4. Queue listing shows correct counts
        resp_queue = client.get(f"/approval/runs/{run_id}/queue")
        assert resp_queue.status_code == 200
        queue_data = resp_queue.json()
        assert queue_data["total"] == 3
        assert queue_data["pending"] == 1  # Only item_untouched remains pending

    def test_already_decided_returns_409(self, client, seeded_queue):
        """Trying to re-decide an already-decided item returns 409."""
        run_id, items = seeded_queue

        # First decision
        client.post(
            f"/approval/items/{items[0].id}/decide",
            json={
                "decision": "approved",
                "reviewer_id": "r1",
                "justification": "ok",
            },
        )

        # Second decision on same item
        response = client.post(
            f"/approval/items/{items[0].id}/decide",
            json={
                "decision": "rejected",
                "reviewer_id": "r2",
                "justification": "nope",
            },
        )

        assert response.status_code == 409

    def test_nonexistent_item_returns_404(self, client):
        """Deciding a nonexistent item returns 404."""
        response = client.post(
            "/approval/items/fake-id-123/decide",
            json={
                "decision": "approved",
                "reviewer_id": "r1",
                "justification": "test",
            },
        )

        assert response.status_code == 404

    def test_invalid_decision_value_returns_422(self, client, seeded_queue):
        """Invalid decision value returns 422."""
        run_id, items = seeded_queue

        response = client.post(
            f"/approval/items/{items[0].id}/decide",
            json={
                "decision": "maybe",
                "reviewer_id": "r1",
                "justification": "unsure",
            },
        )

        assert response.status_code == 422

    def test_empty_justification_returns_422(self, client, seeded_queue):
        """Empty justification returns 422."""
        run_id, items = seeded_queue

        response = client.post(
            f"/approval/items/{items[0].id}/decide",
            json={
                "decision": "approved",
                "reviewer_id": "r1",
                "justification": "",
            },
        )

        assert response.status_code == 422

    def test_list_queue_shows_all_items(self, client, seeded_queue):
        """GET /approval/runs/{run_id}/queue returns all items."""
        run_id, items = seeded_queue

        response = client.get(f"/approval/runs/{run_id}/queue")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        assert data["total"] == 3
        assert data["pending"] == 3
        assert len(data["items"]) == 3
