"""End-to-end resumability test: kill-and-resume with checkpointed state.

Validates the three invariants in docs/invariants.md:
1. Completed node's side effects never re-run on resume.
2. In-flight decisions are not lost (tested via state preservation).
3. No ambiguous run state after kill between node transitions.

This test does NOT require a live LLM key — all nodes are mocked.
It does NOT require a live Postgres — uses an in-memory checkpoint store.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from src.pipeline.config import load_config
from src.pipeline.executor import CrashAfterNode, ResumableExecutor
from src.pipeline.serialization import serialize_state
from src.pipeline.state import PipelineState, create_initial_state


# ---------------------------------------------------------------------------
# In-memory checkpoint store (implements CheckpointStore + ResumeStore)
# ---------------------------------------------------------------------------


class InMemoryCheckpointStore:
    """In-memory store implementing both checkpoint writing and resume reading.

    Used to test the ResumableExecutor without a real database.
    """

    def __init__(self) -> None:
        self.steps: dict[tuple[str, int], dict[str, Any]] = {}
        self._lock_held: dict[str, bool] = {}

    # --- CheckpointStore protocol ---

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

    # --- ResumeStore protocol ---

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

    def release_lock(self, run_id: str) -> None:
        self._lock_held[run_id] = False


# ---------------------------------------------------------------------------
# Side-effect tracking for mock nodes
# ---------------------------------------------------------------------------


class SideEffectTracker:
    """Tracks how many times each node's side effects execute."""

    def __init__(self) -> None:
        self.call_counts: dict[str, int] = {}

    def record(self, node_name: str) -> None:
        self.call_counts[node_name] = self.call_counts.get(node_name, 0) + 1

    def count(self, node_name: str) -> int:
        return self.call_counts.get(node_name, 0)


def make_node_fn(node_name: str, tracker: SideEffectTracker):
    """Create a mock node function that records side-effect execution."""

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResumability:
    """Tests for checkpointed resumability invariants."""

    def _make_initial_state(self, run_id: str) -> PipelineState:
        config = load_config()
        return create_initial_state(
            run_id=run_id,
            document_id=str(uuid.uuid4()),
            document_version_id=str(uuid.uuid4()),
            config=config,
        )

    def test_uninterrupted_run_executes_all_nodes_once(self):
        """Baseline: an uninterrupted run executes each node exactly once."""
        tracker = SideEffectTracker()
        nodes = [
            ("node_a", make_node_fn("node_a", tracker)),
            ("node_b", make_node_fn("node_b", tracker)),
            ("node_c", make_node_fn("node_c", tracker)),
        ]
        store = InMemoryCheckpointStore()
        executor = ResumableExecutor(nodes=nodes, store=store)

        run_id = str(uuid.uuid4())
        state = self._make_initial_state(run_id)

        final_state = executor.run(state)

        assert tracker.count("node_a") == 1
        assert tracker.count("node_b") == 1
        assert tracker.count("node_c") == 1
        assert final_state["completed_nodes"] == ["node_a", "node_b", "node_c"]

    def test_crash_after_first_node_does_not_rerun_on_resume(self):
        """Invariant 1: completed node's side effects never re-run on resume.

        Scenario:
        - Start a 3-node pipeline.
        - Node A completes and is checkpointed.
        - Process crashes after node A checkpoint is durable (before node B starts).
        - Resume with the same run_id and store.
        - Assert node A did NOT execute again.
        - Assert nodes B and C execute exactly once.
        """
        run_id = str(uuid.uuid4())
        store = InMemoryCheckpointStore()

        # --- First execution: crash after node_a checkpoint ---
        tracker_first = SideEffectTracker()
        nodes_first = [
            ("node_a", make_node_fn("node_a", tracker_first)),
            ("node_b", make_node_fn("node_b", tracker_first)),
            ("node_c", make_node_fn("node_c", tracker_first)),
        ]

        executor_first = ResumableExecutor(
            nodes=nodes_first, store=store, crash_after="node_a"
        )
        state = self._make_initial_state(run_id)

        with pytest.raises(CrashAfterNode):
            executor_first.run(state)

        # Node A executed once, then crash
        assert tracker_first.count("node_a") == 1
        assert tracker_first.count("node_b") == 0

        # Verify checkpoint for node_a exists
        checkpoint = store.get_last_checkpoint(run_id)
        assert checkpoint is not None
        assert checkpoint["step_name"] == "node_a"

        # --- Resume execution ---
        store.release_lock(run_id)
        tracker_resume = SideEffectTracker()
        nodes_resume = [
            ("node_a", make_node_fn("node_a", tracker_resume)),
            ("node_b", make_node_fn("node_b", tracker_resume)),
            ("node_c", make_node_fn("node_c", tracker_resume)),
        ]

        executor_resume = ResumableExecutor(nodes=nodes_resume, store=store)
        final_state = executor_resume.run(state)

        # INVARIANT 1: node_a must NOT have re-executed
        assert tracker_resume.count("node_a") == 0, (
            "Completed node 'node_a' re-executed on resume — violates invariant 1"
        )

        # Nodes B and C executed exactly once
        assert tracker_resume.count("node_b") == 1
        assert tracker_resume.count("node_c") == 1

        # Final state contains all nodes completed
        assert "node_a" in final_state["completed_nodes"]
        assert "node_b" in final_state["completed_nodes"]
        assert "node_c" in final_state["completed_nodes"]

    def test_resumed_run_produces_same_final_state_as_uninterrupted(self):
        """Invariant 1+3: resumed run produces identical final state.

        Compares completed_nodes, current_node, node_status from:
        (a) An uninterrupted 3-node run
        (b) A run that crashes after node 1 and resumes
        """
        # --- Uninterrupted run ---
        run_id_clean = str(uuid.uuid4())
        tracker_clean = SideEffectTracker()
        store_clean = InMemoryCheckpointStore()
        nodes_clean = [
            ("node_a", make_node_fn("node_a", tracker_clean)),
            ("node_b", make_node_fn("node_b", tracker_clean)),
            ("node_c", make_node_fn("node_c", tracker_clean)),
        ]
        executor_clean = ResumableExecutor(nodes=nodes_clean, store=store_clean)
        state_clean = self._make_initial_state(run_id_clean)
        final_clean = executor_clean.run(state_clean)

        # --- Crashed + resumed run ---
        run_id_crash = str(uuid.uuid4())
        store_crash = InMemoryCheckpointStore()

        tracker_crash = SideEffectTracker()
        nodes_crash = [
            ("node_a", make_node_fn("node_a", tracker_crash)),
            ("node_b", make_node_fn("node_b", tracker_crash)),
            ("node_c", make_node_fn("node_c", tracker_crash)),
        ]
        executor_crash = ResumableExecutor(
            nodes=nodes_crash, store=store_crash, crash_after="node_a"
        )
        state_crash = self._make_initial_state(run_id_crash)

        with pytest.raises(CrashAfterNode):
            executor_crash.run(state_crash)

        # Resume
        store_crash.release_lock(run_id_crash)
        tracker_resume = SideEffectTracker()
        nodes_resume = [
            ("node_a", make_node_fn("node_a", tracker_resume)),
            ("node_b", make_node_fn("node_b", tracker_resume)),
            ("node_c", make_node_fn("node_c", tracker_resume)),
        ]
        executor_resume = ResumableExecutor(nodes=nodes_resume, store=store_crash)
        final_resumed = executor_resume.run(state_crash)

        # Compare meaningful state fields
        assert final_clean["completed_nodes"] == final_resumed["completed_nodes"]
        assert final_clean["current_node"] == final_resumed["current_node"]
        assert final_clean["node_status"] == final_resumed["node_status"]

    def test_orphaned_running_row_is_cleaned_on_resume(self):
        """Invariant 3: no ambiguous state after kill.

        If a node was mid-execution (status='running') when the process died,
        the resume logic marks it as 'failed' before continuing.
        """
        run_id = str(uuid.uuid4())
        store = InMemoryCheckpointStore()

        state = self._make_initial_state(run_id)

        # Checkpoint node_a as completed
        state_a = PipelineState(
            **{
                **state,
                "current_node": "node_a",
                "node_status": "completed",
                "completed_nodes": ["node_a"],
            }
        )
        store.create_step(run_id, "node_a", 1)
        store.write_checkpoint(
            run_id=run_id,
            step_name="node_a",
            step_order=1,
            output_state=serialize_state(state_a),
            status="completed",
            ended_at=datetime.now(timezone.utc),
        )

        # node_b started but crashed (orphaned running row)
        store.create_step(run_id, "node_b", 2)

        # Verify the orphan exists
        orphan_key = (run_id, 2)
        assert store.steps[orphan_key]["status"] == "running"
        assert store.steps[orphan_key]["ended_at"] is None

        # Mark orphans (what resume logic does)
        orphan_count = store.mark_orphaned_running_as_failed(run_id)

        assert orphan_count == 1
        assert store.steps[orphan_key]["status"] == "failed"

    def test_crash_after_second_node_resumes_from_second(self):
        """Verify resume works correctly when crashing after node 2 of 3."""
        run_id = str(uuid.uuid4())
        store = InMemoryCheckpointStore()

        # First run: crash after node_b
        tracker_first = SideEffectTracker()
        nodes_first = [
            ("node_a", make_node_fn("node_a", tracker_first)),
            ("node_b", make_node_fn("node_b", tracker_first)),
            ("node_c", make_node_fn("node_c", tracker_first)),
        ]
        executor_first = ResumableExecutor(
            nodes=nodes_first, store=store, crash_after="node_b"
        )
        state = self._make_initial_state(run_id)

        with pytest.raises(CrashAfterNode):
            executor_first.run(state)

        assert tracker_first.count("node_a") == 1
        assert tracker_first.count("node_b") == 1
        assert tracker_first.count("node_c") == 0

        # Resume
        store.release_lock(run_id)
        tracker_resume = SideEffectTracker()
        nodes_resume = [
            ("node_a", make_node_fn("node_a", tracker_resume)),
            ("node_b", make_node_fn("node_b", tracker_resume)),
            ("node_c", make_node_fn("node_c", tracker_resume)),
        ]
        executor_resume = ResumableExecutor(nodes=nodes_resume, store=store)
        final_state = executor_resume.run(state)

        # Neither node_a nor node_b should re-execute
        assert tracker_resume.count("node_a") == 0
        assert tracker_resume.count("node_b") == 0
        # Only node_c should execute
        assert tracker_resume.count("node_c") == 1
        assert final_state["completed_nodes"] == ["node_a", "node_b", "node_c"]
