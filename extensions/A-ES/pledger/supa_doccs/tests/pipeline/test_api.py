"""Unit tests for the pipeline API endpoints.

Tests the FastAPI router for creating and resuming pipeline runs using
in-memory store implementations for isolation.
"""

import uuid
from typing import Any, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.pipeline.api import (
    router,
    set_resume_store,
    set_run_store,
)
from src.pipeline.resume import ResumeFromBeginning, ResumeResult
from src.pipeline.state import PipelineState, create_initial_state
from src.pipeline.config import load_config


# --- In-memory store implementations ---


class InMemoryRunStore:
    """In-memory implementation of RunStore for testing."""

    def __init__(self):
        self.runs: dict[str, dict[str, Any]] = {}
        self.locks: set[str] = set()

    def create_run(
        self,
        run_id: str,
        document_id: str,
        document_version_id: str,
        config_snapshot: dict,
    ) -> None:
        self.runs[run_id] = {
            "run_id": run_id,
            "document_id": document_id,
            "document_version_id": document_version_id,
            "config_snapshot": config_snapshot,
        }

    def acquire_run_lock(self, run_id: str) -> bool:
        if run_id in self.locks:
            return False
        self.locks.add(run_id)
        return True

    def run_exists(self, run_id: str) -> bool:
        return run_id in self.runs


class InMemoryResumeStore:
    """In-memory implementation of ResumeStore for testing."""

    def __init__(self):
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.orphaned_counts: dict[str, int] = {}
        self.locks: set[str] = set()
        self._lock_available: bool = True

    def get_last_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        return self.checkpoints.get(run_id)

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        return self.orphaned_counts.get(run_id, 0)

    def acquire_run_lock(self, run_id: str) -> bool:
        if not self._lock_available:
            return False
        self.locks.add(run_id)
        return True

    def set_lock_available(self, available: bool) -> None:
        self._lock_available = available


# --- Test fixtures ---


@pytest.fixture
def run_store():
    """Provide a fresh in-memory run store."""
    return InMemoryRunStore()


@pytest.fixture
def resume_store():
    """Provide a fresh in-memory resume store."""
    return InMemoryResumeStore()


@pytest.fixture
def client(run_store, resume_store):
    """Provide a FastAPI TestClient with stores configured."""
    set_run_store(run_store)
    set_resume_store(resume_store)

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)

    # Clean up global state
    set_run_store(None)
    set_resume_store(None)


# --- POST /runs tests ---


class TestCreateRun:
    """Tests for the POST /runs endpoint."""

    def test_creates_run_with_valid_inputs(self, client, run_store):
        """POST /runs creates a run with valid inputs and returns run_id."""
        response = client.post(
            "/runs",
            json={
                "document_id": "doc-123",
                "document_version_id": "ver-456",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert data["status"] == "created"

        # Verify UUID format
        uuid.UUID(data["run_id"])

        # Verify run was persisted in store
        assert run_store.run_exists(data["run_id"])
        stored = run_store.runs[data["run_id"]]
        assert stored["document_id"] == "doc-123"
        assert stored["document_version_id"] == "ver-456"

    def test_creates_run_with_config_overrides(self, client, run_store):
        """POST /runs accepts config_overrides and freezes them."""
        response = client.post(
            "/runs",
            json={
                "document_id": "doc-123",
                "document_version_id": "ver-456",
                "config_overrides": {"max_retries": 5},
            },
        )

        assert response.status_code == 200
        data = response.json()
        run_id = data["run_id"]
        assert run_store.runs[run_id]["config_snapshot"]["max_retries"] == 5

    def test_validates_required_document_id(self, client):
        """POST /runs returns 422 when document_id is missing."""
        response = client.post(
            "/runs",
            json={
                "document_version_id": "ver-456",
            },
        )

        assert response.status_code == 422

    def test_validates_required_document_version_id(self, client):
        """POST /runs returns 422 when document_version_id is missing."""
        response = client.post(
            "/runs",
            json={
                "document_id": "doc-123",
            },
        )

        assert response.status_code == 422

    def test_validates_empty_document_id(self, client):
        """POST /runs returns 422 when document_id is empty string."""
        response = client.post(
            "/runs",
            json={
                "document_id": "",
                "document_version_id": "ver-456",
            },
        )

        assert response.status_code == 422

    def test_rejects_invalid_config_overrides(self, client):
        """POST /runs returns 422 when config_overrides has invalid keys."""
        response = client.post(
            "/runs",
            json={
                "document_id": "doc-123",
                "document_version_id": "ver-456",
                "config_overrides": {"unknown_key": 42},
            },
        )

        assert response.status_code == 422
        assert "unknown_key" in response.json()["detail"].lower()


# --- POST /runs/{run_id}/resume tests ---


class TestResumeRun:
    """Tests for the POST /runs/{run_id}/resume endpoint."""

    def test_resume_returns_info_no_checkpoint(self, client, resume_store):
        """POST /runs/{run_id}/resume returns resume info when no checkpoint exists."""
        run_id = str(uuid.uuid4())

        response = client.post(f"/runs/{run_id}/resume")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        assert data["status"] == "resumed"
        assert data["resumed_from"] is None
        assert data["next_node"] == "ingest"

    def test_resume_returns_info_with_checkpoint(self, client, resume_store):
        """POST /runs/{run_id}/resume returns correct checkpoint info."""
        run_id = str(uuid.uuid4())

        # Set up a checkpoint at the extract_text node
        config = load_config()
        state = create_initial_state(
            run_id=run_id,
            document_id="doc-1",
            document_version_id="ver-1",
            config=config,
        )
        # Simulate completed extract_text node
        state_dict = dict(state)
        state_dict["current_node"] = "extract_text"
        state_dict["node_status"] = "completed"
        state_dict["completed_nodes"] = ["ingest", "extract_text"]
        state_dict["extracted_text"] = "some text"

        from src.pipeline.serialization import serialize_state

        resume_store.checkpoints[run_id] = {
            "step_name": "extract_text",
            "step_order": 2,
            "output_state": serialize_state(state_dict),
            "status": "completed",
        }

        response = client.post(f"/runs/{run_id}/resume")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        assert data["status"] == "resumed"
        assert data["resumed_from"] == "extract_text"
        assert data["next_node"] == "chunk"

    def test_resume_returns_409_when_lock_held(self, client, resume_store):
        """POST /runs/{run_id}/resume returns 409 when lock is already held."""
        run_id = str(uuid.uuid4())
        resume_store.set_lock_available(False)

        response = client.post(f"/runs/{run_id}/resume")

        assert response.status_code == 409
        assert "lock" in response.json()["detail"].lower()
