"""Concurrency tests: two runs against the same document pile must not corrupt each other.

Validates invariant 4 in docs/invariants.md:
- Two concurrent runs produce correct, non-corrupted, non-duplicated results.
- Each run's checkpoints are fully isolated by run_id.
- No interleaved writes corrupt either run's state.

Uses threading (not asyncio) to exercise true concurrent access against
a shared store. No live LLM key or Postgres required — mocked nodes
and a thread-safe in-memory store.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Optional

import pytest

from src.pipeline.config import load_config
from src.pipeline.executor import ResumableExecutor
from src.pipeline.state import PipelineState, create_initial_state


# ---------------------------------------------------------------------------
# Thread-safe in-memory checkpoint store (implements ExecutorStore protocol)
# ---------------------------------------------------------------------------


class ThreadSafeCheckpointStore:
    """In-memory checkpoint store safe for genuine multi-threaded access.

    Unlike the sequential-test store in test_resumability.py, every operation
    serializes on an internal mutex and per-run_id execution locks are real
    threading.Lock objects (atomic check-and-set), because racing threads is
    exactly what these tests exercise. Step rows are keyed by (run_id,
    step_order) so concurrent runs sharing one store stay fully isolated.
    """

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self.steps: dict[tuple[str, int], dict[str, Any]] = {}
        self._locks: dict[str, threading.Lock] = {}

    def _get_run_lock(self, run_id: str) -> threading.Lock:
        with self._mutex:
            if run_id not in self._locks:
                self._locks[run_id] = threading.Lock()
            return self._locks[run_id]

    def acquire_run_lock(self, run_id: str) -> bool:
        return self._get_run_lock(run_id).acquire(blocking=False)

    def release_run_lock(self, run_id: str) -> None:
        try:
            self._get_run_lock(run_id).release()
        except RuntimeError:
            pass

    def create_step(self, run_id: str, step_name: str, step_order: int) -> None:
        with self._mutex:
            self.steps[(run_id, step_order)] = {
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
        with self._mutex:
            key = (run_id, step_order)
            if key not in self.steps:
                raise RuntimeError(f"Step row not found: {key}")
            row = self.steps[key]
            row["output_state"] = output_state
            row["status"] = status
            row["ended_at"] = ended_at

    def get_last_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._mutex:
            candidates = [
                dict(row)
                for (rid, _), row in self.steps.items()
                if rid == run_id and row["status"] in ("completed", "skipped")
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r["step_order"])

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        with self._mutex:
            count = 0
            for (rid, _), row in self.steps.items():
                if (
                    rid == run_id
                    and row["status"] == "running"
                    and row["ended_at"] is None
                ):
                    row["status"] = "failed"
                    count += 1
            return count


# ---------------------------------------------------------------------------
# Side-effect tracking (thread-safe)
# ---------------------------------------------------------------------------


class ThreadSafeTracker:
    """Thread-safe side-effect tracker for concurrent test assertions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[tuple[str, str]] = []  # (run_id, node_name)

    def record(self, run_id: str, node_name: str) -> None:
        with self._lock:
            self._calls.append((run_id, node_name))

    def calls_for_run(self, run_id: str) -> list[str]:
        with self._lock:
            return [node for rid, node in self._calls if rid == run_id]

    def all_calls(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._calls)


# ---------------------------------------------------------------------------
# Mock node factories
# ---------------------------------------------------------------------------


def make_node_fn(
    node_name: str,
    tracker: ThreadSafeTracker,
    delay: float = 0.0,
):
    """Create a node function that records execution and optionally delays.

    The delay simulates real work and forces thread interleaving to surface
    concurrency bugs.
    """

    def node_fn(state: PipelineState) -> PipelineState:
        run_id = state["run_id"]
        tracker.record(run_id, node_name)

        if delay > 0:
            time.sleep(delay)

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
# Helpers
# ---------------------------------------------------------------------------


def _make_initial_state(run_id: str, document_id: str) -> PipelineState:
    """Create initial state with a specific document_id (simulating same pile)."""
    config = load_config()
    return create_initial_state(
        run_id=run_id,
        document_id=document_id,
        document_version_id=str(uuid.uuid4()),
        config=config,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConcurrentRunIsolation:
    """Tests for invariant 4: concurrent run isolation."""

    def test_two_runs_same_document_both_complete_correctly(self):
        """Two runs against the same document_id complete without corruption.

        Both runs execute 3 nodes concurrently. After both finish:
        - Each run has exactly 3 completed nodes.
        - No node from run A appears in run B's state or vice versa.
        - No duplicate entries.
        """
        document_id = str(uuid.uuid4())
        run_id_a = str(uuid.uuid4())
        run_id_b = str(uuid.uuid4())

        store = ThreadSafeCheckpointStore()
        tracker = ThreadSafeTracker()

        # Small delays to force interleaving
        nodes_a = [
            ("node_a", make_node_fn("node_a", tracker, delay=0.01)),
            ("node_b", make_node_fn("node_b", tracker, delay=0.01)),
            ("node_c", make_node_fn("node_c", tracker, delay=0.01)),
        ]
        nodes_b = [
            ("node_a", make_node_fn("node_a", tracker, delay=0.01)),
            ("node_b", make_node_fn("node_b", tracker, delay=0.01)),
            ("node_c", make_node_fn("node_c", tracker, delay=0.01)),
        ]

        state_a = _make_initial_state(run_id_a, document_id)
        state_b = _make_initial_state(run_id_b, document_id)

        results: dict[str, Optional[PipelineState]] = {"a": None, "b": None}
        errors: dict[str, Optional[Exception]] = {"a": None, "b": None}

        def run_pipeline(key: str, nodes, state):
            try:
                executor = ResumableExecutor(nodes=nodes, store=store)
                results[key] = executor.run(state)
            except Exception as e:
                errors[key] = e

        thread_a = threading.Thread(target=run_pipeline, args=("a", nodes_a, state_a))
        thread_b = threading.Thread(target=run_pipeline, args=("b", nodes_b, state_b))

        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        # No errors
        assert errors["a"] is None, f"Run A failed: {errors['a']}"
        assert errors["b"] is None, f"Run B failed: {errors['b']}"

        # Both completed
        final_a = results["a"]
        final_b = results["b"]
        assert final_a is not None
        assert final_b is not None

        # Each run has exactly its own 3 completed nodes
        assert final_a["completed_nodes"] == ["node_a", "node_b", "node_c"]
        assert final_b["completed_nodes"] == ["node_a", "node_b", "node_c"]

        # Each run's state has correct run_id (not contaminated)
        assert final_a["run_id"] == run_id_a
        assert final_b["run_id"] == run_id_b

    def test_checkpoint_rows_are_scoped_by_run_id(self):
        """Each run's checkpoints are isolated — run A can't see run B's rows."""
        document_id = str(uuid.uuid4())
        run_id_a = str(uuid.uuid4())
        run_id_b = str(uuid.uuid4())

        store = ThreadSafeCheckpointStore()
        tracker = ThreadSafeTracker()

        nodes = [
            ("node_a", make_node_fn("node_a", tracker, delay=0.005)),
            ("node_b", make_node_fn("node_b", tracker, delay=0.005)),
            ("node_c", make_node_fn("node_c", tracker, delay=0.005)),
        ]

        state_a = _make_initial_state(run_id_a, document_id)
        state_b = _make_initial_state(run_id_b, document_id)

        results: dict[str, Optional[PipelineState]] = {"a": None, "b": None}

        def run_pipeline(key: str, state):
            executor = ResumableExecutor(nodes=list(nodes), store=store)
            results[key] = executor.run(state)

        thread_a = threading.Thread(target=run_pipeline, args=("a", state_a))
        thread_b = threading.Thread(target=run_pipeline, args=("b", state_b))

        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        # Verify checkpoint isolation: each run_id has exactly 3 step rows
        steps_a = [
            row for (rid, _), row in store.steps.items() if rid == run_id_a
        ]
        steps_b = [
            row for (rid, _), row in store.steps.items() if rid == run_id_b
        ]

        assert len(steps_a) == 3, f"Run A has {len(steps_a)} steps, expected 3"
        assert len(steps_b) == 3, f"Run B has {len(steps_b)} steps, expected 3"

        # All step rows for run A reference run_id_a
        for row in steps_a:
            assert row["run_id"] == run_id_a
        for row in steps_b:
            assert row["run_id"] == run_id_b

    def test_no_duplicate_node_executions_under_concurrency(self):
        """Under concurrent execution, each node executes exactly once per run."""
        document_id = str(uuid.uuid4())
        run_id_a = str(uuid.uuid4())
        run_id_b = str(uuid.uuid4())

        store = ThreadSafeCheckpointStore()
        tracker = ThreadSafeTracker()

        nodes_a = [
            ("node_a", make_node_fn("node_a", tracker, delay=0.008)),
            ("node_b", make_node_fn("node_b", tracker, delay=0.008)),
            ("node_c", make_node_fn("node_c", tracker, delay=0.008)),
        ]
        nodes_b = [
            ("node_a", make_node_fn("node_a", tracker, delay=0.008)),
            ("node_b", make_node_fn("node_b", tracker, delay=0.008)),
            ("node_c", make_node_fn("node_c", tracker, delay=0.008)),
        ]

        state_a = _make_initial_state(run_id_a, document_id)
        state_b = _make_initial_state(run_id_b, document_id)

        def run_pipeline(nodes, state):
            executor = ResumableExecutor(nodes=nodes, store=store)
            executor.run(state)

        thread_a = threading.Thread(target=run_pipeline, args=(nodes_a, state_a))
        thread_b = threading.Thread(target=run_pipeline, args=(nodes_b, state_b))

        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        # Each run executed each node exactly once
        calls_a = tracker.calls_for_run(run_id_a)
        calls_b = tracker.calls_for_run(run_id_b)

        assert calls_a == ["node_a", "node_b", "node_c"], (
            f"Run A calls: {calls_a}"
        )
        assert calls_b == ["node_a", "node_b", "node_c"], (
            f"Run B calls: {calls_b}"
        )

    def test_many_concurrent_runs_same_pile(self):
        """Stress test: 5 concurrent runs against the same document pile."""
        document_id = str(uuid.uuid4())
        num_runs = 5
        run_ids = [str(uuid.uuid4()) for _ in range(num_runs)]

        store = ThreadSafeCheckpointStore()
        tracker = ThreadSafeTracker()

        results: dict[str, Optional[PipelineState]] = {rid: None for rid in run_ids}
        errors: dict[str, Optional[Exception]] = {rid: None for rid in run_ids}

        def run_pipeline(run_id: str):
            try:
                nodes = [
                    ("node_a", make_node_fn("node_a", tracker, delay=0.005)),
                    ("node_b", make_node_fn("node_b", tracker, delay=0.005)),
                    ("node_c", make_node_fn("node_c", tracker, delay=0.005)),
                ]
                state = _make_initial_state(run_id, document_id)
                executor = ResumableExecutor(nodes=nodes, store=store)
                results[run_id] = executor.run(state)
            except Exception as e:
                errors[run_id] = e

        threads = [
            threading.Thread(target=run_pipeline, args=(rid,))
            for rid in run_ids
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        # All runs completed without error
        for rid in run_ids:
            assert errors[rid] is None, f"Run {rid} failed: {errors[rid]}"
            assert results[rid] is not None, f"Run {rid} produced no result"

        # Each run has correct isolated results
        for rid in run_ids:
            final = results[rid]
            assert final["run_id"] == rid
            assert final["completed_nodes"] == ["node_a", "node_b", "node_c"]

            # Tracker shows exactly 3 calls per run
            calls = tracker.calls_for_run(rid)
            assert calls == ["node_a", "node_b", "node_c"], (
                f"Run {rid} calls: {calls}"
            )

        # Total store rows: 5 runs × 3 nodes = 15 step rows
        assert len(store.steps) == 15

    def test_same_run_id_concurrent_start_is_serialized(self):
        """If two threads try to start the same run_id, only one proceeds.

        The per-run_id lock ensures the second thread either waits or fails.
        This prevents double-execution of the same run.
        """
        run_id = str(uuid.uuid4())
        document_id = str(uuid.uuid4())

        store = ThreadSafeCheckpointStore()
        tracker = ThreadSafeTracker()

        nodes = [
            ("node_a", make_node_fn("node_a", tracker, delay=0.02)),
            ("node_b", make_node_fn("node_b", tracker, delay=0.02)),
            ("node_c", make_node_fn("node_c", tracker, delay=0.02)),
        ]

        state = _make_initial_state(run_id, document_id)

        results: list[Optional[PipelineState]] = [None, None]
        errors: list[Optional[Exception]] = [None, None]

        def run_pipeline(idx: int):
            try:
                executor = ResumableExecutor(nodes=list(nodes), store=store)
                results[idx] = executor.run(state)
            except Exception as e:
                errors[idx] = e

        thread_a = threading.Thread(target=run_pipeline, args=(0,))
        thread_b = threading.Thread(target=run_pipeline, args=(1,))

        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        # At least one should succeed. The other might also succeed (if it
        # ran after the first finished) or might get a lock error.
        successful = [r for r in results if r is not None]
        assert len(successful) >= 1

        # Critical: each node executed at most once per run_id.
        # Even if both threads "ran", the second should have skipped
        # already-checkpointed nodes (per resumability invariant).
        calls = tracker.calls_for_run(run_id)
        node_a_count = calls.count("node_a")
        node_b_count = calls.count("node_b")
        node_c_count = calls.count("node_c")

        # No node should execute more than once for the same run_id
        assert node_a_count <= 1, (
            f"node_a executed {node_a_count} times for same run_id"
        )
        assert node_b_count <= 1, (
            f"node_b executed {node_b_count} times for same run_id"
        )
        assert node_c_count <= 1, (
            f"node_c executed {node_c_count} times for same run_id"
        )
