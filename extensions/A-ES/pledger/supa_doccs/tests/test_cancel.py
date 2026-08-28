"""Tests for cooperative cancellation of pipeline runs.

Validates:
1. A running pipeline stops cleanly when cancel is requested between nodes.
2. Completed checkpoints are preserved after cancellation.
3. A cancelled run can be resumed successfully, continuing from where it left off.
4. The cancel REST endpoint returns the expected response.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from src.pipeline.cancel import clear_cancel, is_cancelled, request_cancel, reset_all
from src.pipeline.config import load_config
from src.pipeline.executor import ResumableExecutor
from src.pipeline.serialization import serialize_state
from src.pipeline.state import PipelineState, create_initial_state


# ---------------------------------------------------------------------------
# In-memory checkpoint store (same pattern as test_resumability.py)
# ---------------------------------------------------------------------------


class InMemoryCheckpointStore:
    """In-memory store for testing the executor without a real database."""

    def __init__(self) -> None:
        self.steps: dict[tuple[str, int], dict[str, Any]] = {}
        self._lock_held: dict[str, bool] = {}

    def create_step(self, run_id: str, step_name: str, step_order: int) -> None:
        key = (run_id, step_order)
        self.steps[key] = {
            "run_id": run_id,
            "step_name": step_name,
            "step_order": step_order,
            "status": "running",
            "output_state": None,
            "ended_at": None,
        }

    def write_checkpoint(
        self,
        run_id: str,
        step_name: str,
        step_order: int,
        output_state: dict[str, Any],
        status: str,
        ended_at: Any,
        **kwargs: Any,
    ) -> None:
        key = (run_id, step_order)
        if key not in self.steps:
            raise RuntimeError(f"Step row not found: {key}")
        self.steps[key]["output_state"] = output_state
        self.steps[key]["status"] = status
        self.steps[key]["ended_at"] = ended_at

    def get_last_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        candidates = [
            row
            for (rid, _), row in self.steps.items()
            if rid == run_id and row["status"] in ("completed", "skipped")
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r["step_order"])

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        count = 0
        for (rid, _), row in self.steps.items():
            if rid == run_id and row["status"] == "running" and row["ended_at"] is None:
                row["status"] = "failed"
                count += 1
        return count

    def acquire_run_lock(self, run_id: str) -> bool:
        if self._lock_held.get(run_id, False):
            return False
        self._lock_held[run_id] = True
        return True

    def release_run_lock(self, run_id: str) -> None:
        self._lock_held[run_id] = False

    def run_exists(self, run_id: str) -> bool:
        return any(rid == run_id for (rid, _) in self.steps.keys())


# ---------------------------------------------------------------------------
# Side-effect tracking mock nodes
# ---------------------------------------------------------------------------


class SideEffectTracker:
    def __init__(self) -> None:
        self.call_counts: dict[str, int] = {}

    def record(self, node_name: str) -> None:
        self.call_counts[node_name] = self.call_counts.get(node_name, 0) + 1

    def count(self, node_name: str) -> int:
        return self.call_counts.get(node_name, 0)


def make_node_fn(node_name: str, tracker: SideEffectTracker):
    """Create a mock node that records execution."""

    def node_fn(state: PipelineState) -> PipelineState:
        tracker.record(node_name)
        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append(node_name)
        return PipelineState(
            **{
                **state,
                "current_node": node_name,
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    return node_fn


def make_cancelling_node(node_name: str, tracker: SideEffectTracker, cancel_run_id: str):
    """Node that requests cancellation of its own run after executing.

    Simulates an external cancel arriving while the pipeline is between nodes.
    The cancel takes effect BEFORE the next node starts.
    """

    def node_fn(state: PipelineState) -> PipelineState:
        tracker.record(node_name)
        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append(node_name)

        # Signal cancellation — executor will see this before the NEXT node
        request_cancel(cancel_run_id)

        return PipelineState(
            **{
                **state,
                "current_node": node_name,
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    return node_fn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cancel_flags():
    """Ensure cancellation flags are clean before and after each test."""
    reset_all()
    yield
    reset_all()


def _make_initial_state(run_id: str) -> PipelineState:
    config = load_config()
    return create_initial_state(
        run_id=run_id,
        document_id=str(uuid.uuid4()),
        document_version_id=str(uuid.uuid4()),
        config=config,
    )


# ---------------------------------------------------------------------------
# Tests: Executor-level cancellation
# ---------------------------------------------------------------------------


class TestCancelExecutor:
    """Tests for cooperative cancellation in ResumableExecutor."""

    def test_cancel_stops_after_current_node(self):
        """Cancelling mid-pipeline stops execution after the cancelling node.

        Scenario:
        - 3-node pipeline (A, B, C).
        - Node A triggers cancel on completion.
        - Executor checks cancel flag before node B → stops.
        - Only node A has executed.
        """
        run_id = str(uuid.uuid4())
        store = InMemoryCheckpointStore()
        tracker = SideEffectTracker()

        nodes = [
            ("node_a", make_cancelling_node("node_a", tracker, run_id)),
            ("node_b", make_node_fn("node_b", tracker)),
            ("node_c", make_node_fn("node_c", tracker)),
        ]

        executor = ResumableExecutor(nodes=nodes, store=store)
        state = _make_initial_state(run_id)

        final_state = executor.run(state)

        # Only node_a executed
        assert tracker.count("node_a") == 1
        assert tracker.count("node_b") == 0
        assert tracker.count("node_c") == 0

        # State reflects cancellation
        assert final_state["node_status"] == "cancelled"

        # Node A's checkpoint is preserved
        checkpoint = store.get_last_checkpoint(run_id)
        assert checkpoint is not None
        assert checkpoint["step_name"] == "node_a"
        assert checkpoint["status"] == "completed"

    def test_checkpoints_preserved_after_cancel(self):
        """Cancellation does not delete any completed checkpoints."""
        run_id = str(uuid.uuid4())
        store = InMemoryCheckpointStore()
        tracker = SideEffectTracker()

        nodes = [
            ("node_a", make_node_fn("node_a", tracker)),
            ("node_b", make_cancelling_node("node_b", tracker, run_id)),
            ("node_c", make_node_fn("node_c", tracker)),
        ]

        executor = ResumableExecutor(nodes=nodes, store=store)
        state = _make_initial_state(run_id)

        final_state = executor.run(state)

        # Nodes A and B ran, C did not
        assert tracker.count("node_a") == 1
        assert tracker.count("node_b") == 1
        assert tracker.count("node_c") == 0

        # Both checkpoints exist
        completed_steps = [
            row for (rid, _), row in store.steps.items()
            if rid == run_id and row["status"] == "completed"
        ]
        assert len(completed_steps) == 2

        step_names = {s["step_name"] for s in completed_steps}
        assert step_names == {"node_a", "node_b"}

    def test_resume_after_cancel_continues_from_checkpoint(self):
        """A cancelled run can be resumed and continues from where it stopped.

        Scenario:
        - 3-node pipeline.
        - Cancel after node B.
        - Clear cancel flag (simulating user calling resume later).
        - Resume → only node C executes.
        - Final state contains all 3 nodes completed.
        """
        run_id = str(uuid.uuid4())
        store = InMemoryCheckpointStore()
        tracker = SideEffectTracker()

        # First execution: cancel after node_b
        nodes = [
            ("node_a", make_node_fn("node_a", tracker)),
            ("node_b", make_cancelling_node("node_b", tracker, run_id)),
            ("node_c", make_node_fn("node_c", tracker)),
        ]

        executor = ResumableExecutor(nodes=nodes, store=store)
        state = _make_initial_state(run_id)

        final_state = executor.run(state)
        assert final_state["node_status"] == "cancelled"
        assert tracker.count("node_c") == 0

        # --- Resume ---
        # Clear the cancel flag (resume endpoint does this)
        clear_cancel(run_id)
        store.release_run_lock(run_id)

        tracker_resume = SideEffectTracker()
        nodes_resume = [
            ("node_a", make_node_fn("node_a", tracker_resume)),
            ("node_b", make_node_fn("node_b", tracker_resume)),
            ("node_c", make_node_fn("node_c", tracker_resume)),
        ]

        executor_resume = ResumableExecutor(nodes=nodes_resume, store=store)
        resumed_state = executor_resume.run(state)

        # Only node_c should have executed on resume
        assert tracker_resume.count("node_a") == 0
        assert tracker_resume.count("node_b") == 0
        assert tracker_resume.count("node_c") == 1

        # Final state has all nodes completed
        assert resumed_state["completed_nodes"] == ["node_a", "node_b", "node_c"]
        assert resumed_state["node_status"] == "completed"

    def test_cancel_before_any_node_returns_immediately(self):
        """If cancel is set before execution starts, the executor returns immediately."""
        run_id = str(uuid.uuid4())
        store = InMemoryCheckpointStore()
        tracker = SideEffectTracker()

        # Pre-set cancel flag
        request_cancel(run_id)

        nodes = [
            ("node_a", make_node_fn("node_a", tracker)),
            ("node_b", make_node_fn("node_b", tracker)),
        ]

        executor = ResumableExecutor(nodes=nodes, store=store)
        state = _make_initial_state(run_id)

        final_state = executor.run(state)

        # No nodes executed
        assert tracker.count("node_a") == 0
        assert tracker.count("node_b") == 0
        assert final_state["node_status"] == "cancelled"


# ---------------------------------------------------------------------------
# Tests: REST endpoint
# ---------------------------------------------------------------------------


class TestCancelEndpoint:
    """Tests for the POST /runs/{run_id}/cancel REST endpoint."""

    def _get_client(self, store: InMemoryCheckpointStore):
        """Create a test client with injected stores."""
        from src.pipeline.api import router, set_run_store

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        set_run_store(store)
        return TestClient(app)

    def test_cancel_returns_200_for_existing_run(self):
        """Cancel endpoint returns 200 with cancelling status."""
        run_id = str(uuid.uuid4())
        store = InMemoryCheckpointStore()

        # Seed a step so run_exists returns True
        store.create_step(run_id, "node_a", 1)

        client = self._get_client(store)
        response = client.post(f"/runs/{run_id}/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        assert data["status"] == "cancelling"
        assert "checkpoints are preserved" in data["message"]

        # Verify the flag is actually set
        assert is_cancelled(run_id) is True

    def test_cancel_returns_404_for_nonexistent_run(self):
        """Cancel endpoint returns 404 when run doesn't exist."""
        store = InMemoryCheckpointStore()
        client = self._get_client(store)

        response = client.post(f"/runs/{str(uuid.uuid4())}/cancel")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Cancel module unit tests
# ---------------------------------------------------------------------------


class TestCancelModule:
    """Unit tests for the cancel flag registry."""

    def test_request_and_check(self):
        run_id = str(uuid.uuid4())
        assert is_cancelled(run_id) is False
        request_cancel(run_id)
        assert is_cancelled(run_id) is True

    def test_clear_cancel(self):
        run_id = str(uuid.uuid4())
        request_cancel(run_id)
        clear_cancel(run_id)
        assert is_cancelled(run_id) is False

    def test_clear_nonexistent_is_safe(self):
        """Clearing a flag that was never set doesn't raise."""
        clear_cancel(str(uuid.uuid4()))

    def test_reset_all(self):
        ids = [str(uuid.uuid4()) for _ in range(3)]
        for rid in ids:
            request_cancel(rid)
        reset_all()
        for rid in ids:
            assert is_cancelled(rid) is False
