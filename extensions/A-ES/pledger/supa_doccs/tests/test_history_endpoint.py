"""Tests for the /runs/{id}/history endpoint and MCP-equivalent service.

Key test: make three sequential changes to a deliverable, assert /history
returns all three in order with correct source attribution. The history is
backed by the audit_events table — never reconstructed from logs.

Tests cover:
1. REST endpoint: GET /runs/{run_id}/history
2. MCP-equivalent: query_run_history() callable
3. Three sequential changes with correct ordering and source attribution
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.pipeline.api import (
    router,
    set_history_store,
    set_resume_store,
    set_run_store,
)
from src.pipeline.deliverable import Deliverable, SectionClaim
from src.pipeline.history_service import (
    AuditedIncrementalEngine,
    InMemoryAuditStore,
    query_run_history,
)
from src.pipeline.incremental import (
    ClaimTypeRetrievalLayer,
    IncrementalUpdateEngine,
    IncrementalUpdateResult,
)
from src.pipeline.approval import ApprovalService, InMemoryApprovalStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_store():
    """Fresh in-memory audit store."""
    return InMemoryAuditStore()


@pytest.fixture
def run_id():
    """Generate a fresh run_id."""
    return str(uuid.uuid4())


@pytest.fixture
def client(audit_store):
    """FastAPI TestClient with the history store configured."""
    set_history_store(audit_store)
    # Set minimal stubs for other stores to avoid 503
    set_run_store(_MinimalRunStore())
    set_resume_store(_MinimalResumeStore())

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)

    # Clean up global state
    set_history_store(None)
    set_run_store(None)
    set_resume_store(None)


class _MinimalRunStore:
    """Minimal stub for run store — not exercised in history tests."""

    def create_run(self, *args, **kwargs):
        pass

    def acquire_run_lock(self, run_id: str) -> bool:
        return True

    def run_exists(self, run_id: str) -> bool:
        return True


class _MinimalResumeStore:
    """Minimal stub for resume store — not exercised in history tests."""

    def get_last_checkpoint(self, run_id: str):
        return None

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        return 0

    def acquire_run_lock(self, run_id: str) -> bool:
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deliverable_with_claims(source_doc_id: str) -> Deliverable:
    """Create a deliverable pre-populated with loan agreement claims."""
    deliverable = Deliverable()
    claims = [
        SectionClaim(
            claim_id="claim-1",
            claim_type="loan_agreement.borrower_name",
            extracted_text="Alice Johnson",
            confidence=0.85,
            source_document_id=source_doc_id,
        ),
        SectionClaim(
            claim_id="claim-2",
            claim_type="loan_agreement.interest_rate",
            extracted_text="12.00",
            confidence=0.85,
            source_document_id=source_doc_id,
        ),
        SectionClaim(
            claim_id="claim-3",
            claim_type="loan_agreement.principal_amount",
            extracted_text="50000.00",
            confidence=0.85,
            source_document_id=source_doc_id,
        ),
    ]
    for claim in claims:
        deliverable.add_claim(claim)
    deliverable.compute_all_hashes()
    return deliverable


def _do_incremental_update_with_audit(
    deliverable: Deliverable,
    new_claims: list[SectionClaim],
    new_document_id: str,
    audit_engine: AuditedIncrementalEngine,
    approval_service: ApprovalService,
    run_id: str,
) -> IncrementalUpdateResult:
    """Run an incremental update and record audit events.

    This simulates the full watcher flow: extract claims, run incremental
    update, emit audit events for all changes.
    """
    engine = IncrementalUpdateEngine(
        retrieval_layer=ClaimTypeRetrievalLayer(),
        approval_service=approval_service,
        run_id=run_id,
    )

    # Capture section state before update for audit
    pre_hashes = {k: list(s.claims) for k, s in deliverable.sections.items()}

    result = engine.update(deliverable, new_claims, new_document_id)

    # Emit audit events for each change
    for section_key in result.sections_updated:
        if section_key in pre_hashes:
            # Section existed before — this is an update
            prev_claims = pre_hashes[section_key]
            audit_engine.record_section_updated(
                section_key=section_key,
                previous_state={
                    "claims": [
                        {"claim_id": c.claim_id, "extracted_text": c.extracted_text}
                        for c in prev_claims
                    ]
                },
                new_state={
                    "claims": [
                        {"claim_id": c.claim_id, "extracted_text": c.extracted_text}
                        for c in deliverable.sections[section_key].claims
                    ]
                },
                source_document_id=new_document_id,
            )
        else:
            # New section — this is a creation
            audit_engine.record_section_created(
                section_key=section_key,
                new_state={
                    "claims": [
                        {"claim_id": c.claim_id, "extracted_text": c.extracted_text}
                        for c in deliverable.sections[section_key].claims
                    ]
                },
                source_document_id=new_document_id,
            )

    for conflict in result.conflicts:
        audit_engine.record_conflict_detected(
            section_key=conflict.section_key,
            conflict_details={
                "existing_value": conflict.existing_claim.extracted_text,
                "new_value": conflict.new_claim.extracted_text,
                "reason": conflict.reason,
            },
            source_document_id=new_document_id,
        )

    return result


# ---------------------------------------------------------------------------
# Test: Three sequential changes → /history returns all three in order
# ---------------------------------------------------------------------------


class TestHistoryThreeSequentialChanges:
    """Prove /history returns all changes in order with source attribution.

    Scenario:
    1. Document A creates the initial deliverable (loan agreement claims).
    2. Document B adds a repayment section (new section creation).
    3. Document C updates the repayment section (non-conflicting update).

    Assert: GET /runs/{run_id}/history returns exactly 3 events, in
    chronological order, each with the correct source_document_id.
    """

    def test_three_sequential_changes_returned_in_order_via_rest(
        self, client, audit_store, run_id
    ):
        """REST endpoint: 3 changes → 3 events in order with source attribution."""
        # --- Setup ---
        source_doc_a = str(uuid.uuid4())
        source_doc_b = str(uuid.uuid4())
        source_doc_c = str(uuid.uuid4())

        deliverable = _make_deliverable_with_claims(source_doc_a)
        approval_store = InMemoryApprovalStore()
        approval_service = ApprovalService(approval_store)
        audit_engine = AuditedIncrementalEngine(
            audit_store=audit_store,
            run_id=run_id,
        )

        # --- Change 1: Document A creates initial sections ---
        # Record the initial creation as audit events
        t1 = datetime(2024, 1, 10, 10, 0, 0, tzinfo=timezone.utc)
        audit_store.append_event(
            run_id=run_id,
            entity_type="section",
            entity_id="loan_agreement.borrower_name",
            action="created",
            actor_id="watcher",
            new_state={
                "claims": [{"claim_id": "claim-1", "extracted_text": "Alice Johnson"}]
            },
            source_ref=source_doc_a,
            event_timestamp=t1,
        )

        # --- Change 2: Document B adds repayment section ---
        t2 = datetime(2024, 1, 10, 11, 0, 0, tzinfo=timezone.utc)
        new_claims_b = [
            SectionClaim(
                claim_id="claim-b1",
                claim_type="repayment_statement.amount_paid",
                extracted_text="5000.00",
                confidence=0.9,
                source_document_id=source_doc_b,
            ),
        ]

        _do_incremental_update_with_audit(
            deliverable=deliverable,
            new_claims=new_claims_b,
            new_document_id=source_doc_b,
            audit_engine=audit_engine,
            approval_service=approval_service,
            run_id=run_id,
        )

        # Manually set timestamp for deterministic ordering
        # (the last event is the one just created)
        audit_store._events[-1]["event_timestamp"] = t2

        # --- Change 3: Document C updates the repayment section ---
        t3 = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
        new_claims_c = [
            SectionClaim(
                claim_id="claim-c1",
                claim_type="repayment_statement.amount_paid",
                extracted_text="5000.00",  # Same value — non-conflicting update
                confidence=0.95,
                source_document_id=source_doc_c,
            ),
        ]

        _do_incremental_update_with_audit(
            deliverable=deliverable,
            new_claims=new_claims_c,
            new_document_id=source_doc_c,
            audit_engine=audit_engine,
            approval_service=approval_service,
            run_id=run_id,
        )

        # Manually set timestamp for deterministic ordering
        audit_store._events[-1]["event_timestamp"] = t3

        # --- Assert via REST endpoint ---
        response = client.get(f"/runs/{run_id}/history")
        assert response.status_code == 200

        data = response.json()
        assert data["run_id"] == run_id
        assert data["total"] == 3

        entries = data["entries"]
        assert len(entries) == 3

        # Entry 1: Document A created a section
        assert entries[0]["entity_type"] == "section"
        assert entries[0]["entity_id"] == "loan_agreement.borrower_name"
        assert entries[0]["action"] == "created"
        assert entries[0]["source_document_id"] == source_doc_a
        assert entries[0]["actor_id"] == "watcher"

        # Entry 2: Document B created a new repayment section
        assert entries[1]["entity_type"] == "section"
        assert entries[1]["entity_id"] == "repayment_statement.amount_paid"
        assert entries[1]["action"] == "created"
        assert entries[1]["source_document_id"] == source_doc_b

        # Entry 3: Document C updated the repayment section
        assert entries[2]["entity_type"] == "section"
        assert entries[2]["entity_id"] == "repayment_statement.amount_paid"
        assert entries[2]["action"] == "updated"
        assert entries[2]["source_document_id"] == source_doc_c

        # Verify chronological order
        t1_str = entries[0]["timestamp"]
        t2_str = entries[1]["timestamp"]
        t3_str = entries[2]["timestamp"]
        assert t1_str < t2_str < t3_str

    def test_three_sequential_changes_returned_in_order_via_mcp(
        self, audit_store, run_id
    ):
        """MCP-equivalent: 3 changes → 3 events in order with source attribution."""
        source_doc_a = str(uuid.uuid4())
        source_doc_b = str(uuid.uuid4())
        source_doc_c = str(uuid.uuid4())

        deliverable = _make_deliverable_with_claims(source_doc_a)
        approval_store = InMemoryApprovalStore()
        approval_service = ApprovalService(approval_store)
        audit_engine = AuditedIncrementalEngine(
            audit_store=audit_store,
            run_id=run_id,
        )

        # Change 1: Initial creation
        t1 = datetime(2024, 2, 1, 8, 0, 0, tzinfo=timezone.utc)
        audit_store.append_event(
            run_id=run_id,
            entity_type="section",
            entity_id="loan_agreement.interest_rate",
            action="created",
            actor_id="watcher",
            new_state={"claims": [{"claim_id": "claim-2", "extracted_text": "12.00"}]},
            source_ref=source_doc_a,
            event_timestamp=t1,
        )

        # Change 2: Add modification section
        t2 = datetime(2024, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
        new_claims_b = [
            SectionClaim(
                claim_id="mod-1",
                claim_type="modification_agreement.effective_date",
                extracted_text="2024-03-01",
                confidence=0.9,
                source_document_id=source_doc_b,
            ),
        ]
        _do_incremental_update_with_audit(
            deliverable=deliverable,
            new_claims=new_claims_b,
            new_document_id=source_doc_b,
            audit_engine=audit_engine,
            approval_service=approval_service,
            run_id=run_id,
        )
        audit_store._events[-1]["event_timestamp"] = t2

        # Change 3: Update modification section
        t3 = datetime(2024, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
        new_claims_c = [
            SectionClaim(
                claim_id="mod-2",
                claim_type="modification_agreement.effective_date",
                extracted_text="2024-03-01",  # Same value, different source
                confidence=0.95,
                source_document_id=source_doc_c,
            ),
        ]
        _do_incremental_update_with_audit(
            deliverable=deliverable,
            new_claims=new_claims_c,
            new_document_id=source_doc_c,
            audit_engine=audit_engine,
            approval_service=approval_service,
            run_id=run_id,
        )
        audit_store._events[-1]["event_timestamp"] = t3

        # --- Query via MCP-equivalent function ---
        result = query_run_history(store=audit_store, run_id=run_id)

        assert result.success is True
        assert result.run_id == run_id
        assert result.total == 3

        entries = result.entries
        assert len(entries) == 3

        # Verify ordering
        assert entries[0]["timestamp"] < entries[1]["timestamp"]
        assert entries[1]["timestamp"] < entries[2]["timestamp"]

        # Verify source attribution
        assert entries[0]["source_document_id"] == source_doc_a
        assert entries[1]["source_document_id"] == source_doc_b
        assert entries[2]["source_document_id"] == source_doc_c

        # Verify content
        assert entries[0]["action"] == "created"
        assert entries[1]["action"] == "created"
        assert entries[2]["action"] == "updated"


# ---------------------------------------------------------------------------
# Additional tests for endpoint behavior
# ---------------------------------------------------------------------------


class TestHistoryEndpointBehavior:
    """Tests for endpoint edge cases and response format."""

    def test_empty_history_returns_zero_entries(self, client, run_id):
        """A run with no events returns an empty list."""
        response = client.get(f"/runs/{run_id}/history")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["entries"] == []
        assert data["run_id"] == run_id

    def test_history_includes_previous_state_for_updates(
        self, client, audit_store, run_id
    ):
        """Updated entries include previous_state showing what was before."""
        audit_store.append_event(
            run_id=run_id,
            entity_type="section",
            entity_id="loan_agreement.interest_rate",
            action="updated",
            actor_id="watcher",
            new_state={"extracted_text": "18.00"},
            previous_state={"extracted_text": "12.00"},
            source_ref="doc-xyz",
        )

        response = client.get(f"/runs/{run_id}/history")
        data = response.json()

        assert data["total"] == 1
        entry = data["entries"][0]
        assert entry["previous_state"] == {"extracted_text": "12.00"}
        assert entry["new_state"] == {"extracted_text": "18.00"}

    def test_history_does_not_include_other_runs_events(
        self, client, audit_store, run_id
    ):
        """Events from other runs are not included."""
        other_run_id = str(uuid.uuid4())

        # Add event to our run
        audit_store.append_event(
            run_id=run_id,
            entity_type="section",
            entity_id="s1",
            action="created",
            actor_id="watcher",
            new_state={"value": "ours"},
            source_ref="doc-1",
        )

        # Add event to another run
        audit_store.append_event(
            run_id=other_run_id,
            entity_type="section",
            entity_id="s2",
            action="created",
            actor_id="watcher",
            new_state={"value": "theirs"},
            source_ref="doc-2",
        )

        response = client.get(f"/runs/{run_id}/history")
        data = response.json()

        assert data["total"] == 1
        assert data["entries"][0]["new_state"]["value"] == "ours"

    def test_history_source_document_id_correctly_attributed(
        self, client, audit_store, run_id
    ):
        """Each entry's source_document_id points to the document that caused it."""
        doc_1 = str(uuid.uuid4())
        doc_2 = str(uuid.uuid4())

        audit_store.append_event(
            run_id=run_id,
            entity_type="section",
            entity_id="s1",
            action="created",
            actor_id="watcher",
            new_state={},
            source_ref=doc_1,
            event_timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        audit_store.append_event(
            run_id=run_id,
            entity_type="section",
            entity_id="s2",
            action="created",
            actor_id="watcher",
            new_state={},
            source_ref=doc_2,
            event_timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )

        response = client.get(f"/runs/{run_id}/history")
        entries = response.json()["entries"]

        assert entries[0]["source_document_id"] == doc_1
        assert entries[1]["source_document_id"] == doc_2


class TestMCPEquivalentService:
    """Tests for the MCP-equivalent query_run_history callable."""

    def test_returns_same_data_as_rest_endpoint(self, audit_store, run_id):
        """MCP function returns the same data shape as the REST endpoint."""
        doc_id = str(uuid.uuid4())
        audit_store.append_event(
            run_id=run_id,
            entity_type="claim",
            entity_id="claim-1",
            action="created",
            actor_id="extract_claims",
            new_state={"extracted_text": "12.00", "claim_type": "interest_rate"},
            source_ref=doc_id,
        )

        result = query_run_history(store=audit_store, run_id=run_id)

        assert result.success is True
        assert result.total == 1
        assert len(result.entries) == 1

        entry = result.entries[0]
        assert entry["entity_type"] == "claim"
        assert entry["entity_id"] == "claim-1"
        assert entry["action"] == "created"
        assert entry["source_document_id"] == doc_id
        assert entry["actor_id"] == "extract_claims"
        assert entry["new_state"]["extracted_text"] == "12.00"

    def test_handles_empty_run_gracefully(self, audit_store):
        """MCP function handles a run with no events."""
        result = query_run_history(store=audit_store, run_id="nonexistent")

        assert result.success is True
        assert result.total == 0
        assert result.entries == []

    def test_chronological_ordering(self, audit_store, run_id):
        """MCP function returns events in chronological order."""
        t1 = datetime(2024, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
        t3 = datetime(2024, 3, 1, 10, 0, 0, tzinfo=timezone.utc)

        # Insert out of order to verify sorting
        audit_store.append_event(
            run_id=run_id,
            entity_type="section",
            entity_id="s3",
            action="created",
            actor_id="watcher",
            new_state={"order": 3},
            source_ref="doc-3",
            event_timestamp=t3,
        )
        audit_store.append_event(
            run_id=run_id,
            entity_type="section",
            entity_id="s1",
            action="created",
            actor_id="watcher",
            new_state={"order": 1},
            source_ref="doc-1",
            event_timestamp=t1,
        )
        audit_store.append_event(
            run_id=run_id,
            entity_type="section",
            entity_id="s2",
            action="created",
            actor_id="watcher",
            new_state={"order": 2},
            source_ref="doc-2",
            event_timestamp=t2,
        )

        result = query_run_history(store=audit_store, run_id=run_id)

        assert result.total == 3
        assert result.entries[0]["new_state"]["order"] == 1
        assert result.entries[1]["new_state"]["order"] == 2
        assert result.entries[2]["new_state"]["order"] == 3
