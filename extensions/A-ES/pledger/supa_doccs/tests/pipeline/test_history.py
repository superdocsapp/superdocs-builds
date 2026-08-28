"""Tests for the /runs/{id}/history endpoint.

Validates that the history endpoint:
- Returns audit events in chronological order
- Includes correct source document attribution (source_ref)
- Reflects all changes made to a deliverable

The test makes three sequential changes to a deliverable and asserts
/history returns all three in order with correct source attribution.

This is backed by the audit_events table — not reconstructed from logs.
"""

from __future__ import annotations

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
from src.pipeline.history import HistoryStore, get_run_history


# --- In-memory history store ---


class InMemoryHistoryStore:
    """In-memory implementation of HistoryStore for testing.

    Stores audit events as dicts and filters/sorts by run_id.
    Simulates the append-only audit_events table.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append_event(
        self,
        run_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_id: str,
        new_state: dict[str, Any],
        previous_state: Optional[dict[str, Any]] = None,
        source_ref: Optional[str] = None,
        event_timestamp: Optional[datetime] = None,
    ) -> str:
        """Append an audit event (simulates INSERT into audit_events).

        Args:
            run_id: The pipeline run this event belongs to.
            entity_type: Type of entity changed.
            entity_id: ID of the entity changed.
            action: The action performed.
            actor_id: Who performed the action.
            new_state: State after the change.
            previous_state: State before the change (None for creates).
            source_ref: Source document reference (document_version_id).
            event_timestamp: When the event occurred (defaults to now).

        Returns:
            The generated event ID.
        """
        event_id = str(uuid.uuid4())
        self.events.append(
            {
                "id": event_id,
                "event_timestamp": event_timestamp or datetime.now(timezone.utc),
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "actor_id": actor_id,
                "previous_state": previous_state,
                "new_state": {**new_state, "run_id": run_id},
                "source_ref": source_ref,
                "_run_id": run_id,  # Internal field for filtering
            }
        )
        return event_id

    def get_events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return all audit events for a run, ordered by timestamp ascending."""
        matching = [
            e for e in self.events if e["_run_id"] == run_id
        ]
        return sorted(matching, key=lambda e: e["event_timestamp"])


# --- Minimal stores for other dependencies ---


class MinimalRunStore:
    """Minimal run store — just enough to mount the router without errors."""

    def create_run(self, **kwargs: Any) -> None:
        pass

    def acquire_run_lock(self, run_id: str) -> bool:
        return True

    def run_exists(self, run_id: str) -> bool:
        return True


class MinimalResumeStore:
    """Minimal resume store."""

    def get_last_checkpoint(self, run_id: str) -> None:
        return None

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        return 0

    def acquire_run_lock(self, run_id: str) -> bool:
        return True


# --- Fixtures ---


@pytest.fixture
def history_store() -> InMemoryHistoryStore:
    """Provide a fresh in-memory history store."""
    return InMemoryHistoryStore()


@pytest.fixture
def client(history_store: InMemoryHistoryStore) -> TestClient:
    """Provide a FastAPI TestClient with history store configured."""
    set_run_store(MinimalRunStore())
    set_resume_store(MinimalResumeStore())
    set_history_store(history_store)

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)

    # Clean up global state
    set_run_store(None)
    set_resume_store(None)
    set_history_store(None)


# --- Tests ---


class TestRunHistory:
    """Tests for GET /runs/{run_id}/history."""

    def test_empty_history_returns_empty_list(self, client: TestClient):
        """A run with no audit events returns an empty history."""
        run_id = str(uuid.uuid4())

        response = client.get(f"/runs/{run_id}/history")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        assert data["entries"] == []
        assert data["total"] == 0

    def test_three_sequential_changes_returned_in_order_with_source_attribution(
        self,
        client: TestClient,
        history_store: InMemoryHistoryStore,
    ):
        """Three sequential changes to a deliverable appear in order with correct source docs.

        Scenario:
        1. Run is created because of source document A
        2. A claim is extracted because of source document A
        3. The claim verdict is updated because of source document B
           (e.g., a modification agreement changes the assessment)

        Each event references the source document that caused the change.
        """
        run_id = str(uuid.uuid4())
        claim_id = str(uuid.uuid4())
        source_doc_a = str(uuid.uuid4())  # Original loan agreement
        source_doc_b = str(uuid.uuid4())  # Modification agreement

        base_time = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)

        # Event 1: Run created (triggered by source document A)
        history_store.append_event(
            run_id=run_id,
            entity_type="run",
            entity_id=run_id,
            action="created",
            actor_id="pipeline:ingest",
            new_state={"status": "running", "document_id": "doc-1"},
            previous_state=None,
            source_ref=source_doc_a,
            event_timestamp=base_time,
        )

        # Event 2: Claim extracted (triggered by source document A)
        history_store.append_event(
            run_id=run_id,
            entity_type="claim",
            entity_id=claim_id,
            action="created",
            actor_id="pipeline:extract_claims",
            new_state={
                "claim_id": claim_id,
                "claim_text": "APR is 24%",
                "verdict": None,
            },
            previous_state=None,
            source_ref=source_doc_a,
            event_timestamp=base_time + timedelta(seconds=30),
        )

        # Event 3: Claim verdict updated (triggered by source document B)
        history_store.append_event(
            run_id=run_id,
            entity_type="claim",
            entity_id=claim_id,
            action="updated",
            actor_id="pipeline:match_rules",
            new_state={
                "claim_id": claim_id,
                "claim_text": "APR is 24%",
                "verdict": "non_compliant",
            },
            previous_state={
                "claim_id": claim_id,
                "claim_text": "APR is 24%",
                "verdict": None,
            },
            source_ref=source_doc_b,
            event_timestamp=base_time + timedelta(seconds=60),
        )

        # Query history endpoint
        response = client.get(f"/runs/{run_id}/history")

        assert response.status_code == 200
        data = response.json()

        assert data["run_id"] == run_id
        assert data["total"] == 3
        assert len(data["entries"]) == 3

        # Verify chronological ordering
        entries = data["entries"]
        timestamps = [e["timestamp"] for e in entries]
        assert timestamps == sorted(timestamps), (
            "History entries must be in chronological order"
        )

        # Entry 1: Run created, source = doc A
        assert entries[0]["entity_type"] == "run"
        assert entries[0]["entity_id"] == run_id
        assert entries[0]["action"] == "created"
        assert entries[0]["actor_id"] == "pipeline:ingest"
        assert entries[0]["source_document_id"] == source_doc_a
        assert entries[0]["previous_state"] is None
        assert entries[0]["new_state"]["status"] == "running"

        # Entry 2: Claim created, source = doc A
        assert entries[1]["entity_type"] == "claim"
        assert entries[1]["entity_id"] == claim_id
        assert entries[1]["action"] == "created"
        assert entries[1]["actor_id"] == "pipeline:extract_claims"
        assert entries[1]["source_document_id"] == source_doc_a
        assert entries[1]["new_state"]["claim_text"] == "APR is 24%"

        # Entry 3: Claim updated, source = doc B (different document!)
        assert entries[2]["entity_type"] == "claim"
        assert entries[2]["entity_id"] == claim_id
        assert entries[2]["action"] == "updated"
        assert entries[2]["actor_id"] == "pipeline:match_rules"
        assert entries[2]["source_document_id"] == source_doc_b
        assert entries[2]["previous_state"]["verdict"] is None
        assert entries[2]["new_state"]["verdict"] == "non_compliant"

    def test_history_only_returns_events_for_requested_run(
        self,
        client: TestClient,
        history_store: InMemoryHistoryStore,
    ):
        """History for run A does not include events from run B."""
        run_a = str(uuid.uuid4())
        run_b = str(uuid.uuid4())
        source_doc = str(uuid.uuid4())

        history_store.append_event(
            run_id=run_a,
            entity_type="run",
            entity_id=run_a,
            action="created",
            actor_id="pipeline:ingest",
            new_state={"status": "running"},
            source_ref=source_doc,
        )
        history_store.append_event(
            run_id=run_b,
            entity_type="run",
            entity_id=run_b,
            action="created",
            actor_id="pipeline:ingest",
            new_state={"status": "running"},
            source_ref=source_doc,
        )

        response = client.get(f"/runs/{run_a}/history")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["entries"][0]["entity_id"] == run_a

    def test_history_includes_all_entity_types(
        self,
        client: TestClient,
        history_store: InMemoryHistoryStore,
    ):
        """History captures changes across different entity types."""
        run_id = str(uuid.uuid4())
        claim_id = str(uuid.uuid4())
        decision_id = str(uuid.uuid4())
        source_doc = str(uuid.uuid4())

        history_store.append_event(
            run_id=run_id,
            entity_type="run",
            entity_id=run_id,
            action="created",
            actor_id="pipeline:ingest",
            new_state={"status": "running"},
            source_ref=source_doc,
        )
        history_store.append_event(
            run_id=run_id,
            entity_type="claim",
            entity_id=claim_id,
            action="created",
            actor_id="pipeline:extract_claims",
            new_state={"claim_text": "Rate is 24%"},
            source_ref=source_doc,
        )
        history_store.append_event(
            run_id=run_id,
            entity_type="decision",
            entity_id=decision_id,
            action="created",
            actor_id="reviewer:bot-alpha",
            new_state={"decision": "approved"},
            source_ref=source_doc,
        )

        response = client.get(f"/runs/{run_id}/history")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        entity_types = [e["entity_type"] for e in data["entries"]]
        assert "run" in entity_types
        assert "claim" in entity_types
        assert "decision" in entity_types


class TestHistoryService:
    """Tests for the history service layer directly (no HTTP)."""

    def test_get_run_history_returns_ordered_entries(self):
        """get_run_history returns entries in chronological order."""
        store = InMemoryHistoryStore()
        run_id = str(uuid.uuid4())
        source_doc = str(uuid.uuid4())

        base_time = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)

        # Insert in reverse order to verify sorting
        store.append_event(
            run_id=run_id,
            entity_type="claim",
            entity_id=str(uuid.uuid4()),
            action="updated",
            actor_id="pipeline:match_rules",
            new_state={"verdict": "fail"},
            source_ref=source_doc,
            event_timestamp=base_time + timedelta(minutes=5),
        )
        store.append_event(
            run_id=run_id,
            entity_type="run",
            entity_id=run_id,
            action="created",
            actor_id="pipeline:ingest",
            new_state={"status": "running"},
            source_ref=source_doc,
            event_timestamp=base_time,
        )

        history = get_run_history(store, run_id)

        assert history.total == 2
        assert history.entries[0].entity_type == "run"
        assert history.entries[1].entity_type == "claim"
        assert history.entries[0].timestamp < history.entries[1].timestamp

    def test_get_run_history_preserves_source_attribution(self):
        """get_run_history preserves source_ref as source_document_id."""
        store = InMemoryHistoryStore()
        run_id = str(uuid.uuid4())
        source_doc_a = "doc-version-aaa"
        source_doc_b = "doc-version-bbb"

        store.append_event(
            run_id=run_id,
            entity_type="run",
            entity_id=run_id,
            action="created",
            actor_id="system",
            new_state={"status": "created"},
            source_ref=source_doc_a,
        )
        store.append_event(
            run_id=run_id,
            entity_type="claim",
            entity_id=str(uuid.uuid4()),
            action="updated",
            actor_id="system",
            new_state={"verdict": "compliant"},
            source_ref=source_doc_b,
        )

        history = get_run_history(store, run_id)

        assert history.entries[0].source_document_id == source_doc_a
        assert history.entries[1].source_document_id == source_doc_b
