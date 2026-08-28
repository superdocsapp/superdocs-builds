"""Tests for the pipeline resume logic.

Tests resume_run using in-memory ResumeStore implementations,
covering checkpoint restoration, orphan cleanup, lock acquisition,
restart from beginning, and correct next-node routing.

Requirements: 6.3, 6.8
"""

from typing import Any, Optional

import pytest

from src.pipeline.config import load_config
from src.pipeline.resume import (
    ResumeFromBeginning,
    ResumeLockError,
    ResumeResult,
    ResumeStore,
    resume_run,
)
from src.pipeline.serialization import serialize_state
from src.pipeline.state import PipelineState, QueueBuckets, create_initial_state


# --- In-memory ResumeStore implementations ---


class InMemoryResumeStore:
    """In-memory implementation of ResumeStore for unit tests."""

    def __init__(
        self,
        checkpoint: Optional[dict[str, Any]] = None,
        orphaned_count: int = 0,
        lock_available: bool = True,
    ) -> None:
        self.checkpoint = checkpoint
        self.orphaned_count = orphaned_count
        self.lock_available = lock_available
        self.lock_acquired_for: Optional[str] = None
        self.orphans_marked_for: Optional[str] = None

    def get_last_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        return self.checkpoint

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        self.orphans_marked_for = run_id
        return self.orphaned_count

    def acquire_run_lock(self, run_id: str) -> bool:
        self.lock_acquired_for = run_id
        return self.lock_available


class LockedResumeStore(InMemoryResumeStore):
    """ResumeStore where the lock is already held (simulates concurrent execution)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(lock_available=False, **kwargs)


# --- Helpers ---


def _make_checkpoint_state(
    node_name: str,
    run_id: str = "run-001",
    node_status: str = "completed",
) -> PipelineState:
    """Create a PipelineState that simulates completing a given node."""
    config = load_config()
    state = create_initial_state(
        run_id=run_id,
        document_id="doc-001",
        document_version_id="ver-001",
        config=config,
    )
    state["current_node"] = node_name
    state["node_status"] = node_status  # type: ignore[typeddict-item]
    state["completed_nodes"] = [node_name]
    return state


def _make_checkpoint_dict(
    node_name: str,
    step_order: int = 1,
    run_id: str = "run-001",
    node_status: str = "completed",
) -> dict[str, Any]:
    """Create a checkpoint dict as returned by get_last_checkpoint."""
    state = _make_checkpoint_state(node_name, run_id, node_status)
    return {
        "step_name": node_name,
        "step_order": step_order,
        "output_state": serialize_state(state),
        "status": node_status,
    }


# --- Tests for successful resume from a checkpoint ---


class TestResumeFromCheckpoint:
    """Tests for resuming from an existing checkpoint."""

    def test_resume_from_ingest_checkpoint(self):
        """After ingest completes, next node should be extract_text."""
        checkpoint = _make_checkpoint_dict("ingest", step_order=1)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "extract_text"
        assert result.resumed_from_step == "ingest"

    def test_resume_from_extract_text_checkpoint(self):
        """After extract_text completes, next node should be chunk."""
        checkpoint = _make_checkpoint_dict("extract_text", step_order=2)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "chunk"

    def test_resume_from_chunk_checkpoint(self):
        """After chunk completes, next node should be embed."""
        checkpoint = _make_checkpoint_dict("chunk", step_order=3)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "embed"

    def test_resume_from_embed_checkpoint(self):
        """After embed completes, next node should be extract_claims."""
        checkpoint = _make_checkpoint_dict("embed", step_order=4)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "extract_claims"

    def test_resume_from_score_confidence_checkpoint(self):
        """After score_confidence completes, next node should be route_to_queue."""
        checkpoint = _make_checkpoint_dict("score_confidence", step_order=7)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "route_to_queue"

    def test_resume_restores_deserialized_state(self):
        """The returned state should be a properly deserialized PipelineState."""
        checkpoint = _make_checkpoint_dict("ingest", step_order=1)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.state["run_id"] == "run-001"
        assert result.state["current_node"] == "ingest"
        assert result.state["node_status"] == "completed"


# --- Tests for identifying correct last checkpoint ---


class TestLastCheckpointIdentification:
    """Tests for correct checkpoint selection."""

    def test_uses_checkpoint_with_highest_step_order(self):
        """The store returns the highest step_order checkpoint; verify resume uses it."""
        # Simulate that embed (step 4) is the last completed step
        checkpoint = _make_checkpoint_dict("embed", step_order=4)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.resumed_from_step == "embed"
        assert result.next_node == "extract_claims"

    def test_skipped_node_is_valid_checkpoint(self):
        """A skipped node checkpoint is a valid resume point."""
        checkpoint = _make_checkpoint_dict(
            "extract_text", step_order=2, node_status="skipped"
        )
        # For skipped status, we need valid skipped_nodes entry
        state = _make_checkpoint_state("extract_text", node_status="skipped")
        state["skipped_nodes"] = [
            {"node_name": "extract_text", "reason": "input_already_text"}
        ]
        checkpoint["output_state"] = serialize_state(state)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.resumed_from_step == "extract_text"
        # Skipped with valid reason → "next" → chunk
        assert result.next_node == "chunk"


# --- Tests for orphaned running rows ---


class TestOrphanedRunningRows:
    """Tests for marking orphaned 'running' rows as failed."""

    def test_orphaned_rows_are_marked_before_resume(self):
        """Orphaned running rows should be marked as failed."""
        checkpoint = _make_checkpoint_dict("ingest", step_order=1)
        store = InMemoryResumeStore(checkpoint=checkpoint, orphaned_count=2)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.orphaned_count == 2
        assert store.orphans_marked_for == "run-001"

    def test_orphaned_rows_marked_even_when_no_checkpoint(self):
        """Orphaned rows are cleaned up even when starting from beginning."""
        store = InMemoryResumeStore(checkpoint=None, orphaned_count=1)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeFromBeginning)
        assert result.orphaned_count == 1
        assert store.orphans_marked_for == "run-001"

    def test_zero_orphaned_rows(self):
        """Normal case: no orphaned rows to clean up."""
        checkpoint = _make_checkpoint_dict("chunk", step_order=3)
        store = InMemoryResumeStore(checkpoint=checkpoint, orphaned_count=0)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.orphaned_count == 0


# --- Tests for lock acquisition failure ---


class TestLockAcquisitionFailure:
    """Tests for advisory lock enforcement."""

    def test_lock_failure_raises_resume_lock_error(self):
        """If the lock is already held, resume_run raises ResumeLockError."""
        store = LockedResumeStore()

        with pytest.raises(ResumeLockError, match="exclusive lock already held"):
            resume_run(store, "run-001")

    def test_lock_failure_includes_run_id_in_message(self):
        """Error message should include the run_id for debugging."""
        store = LockedResumeStore()

        with pytest.raises(ResumeLockError, match="run-042"):
            resume_run(store, "run-042")

    def test_lock_failure_does_not_mark_orphans(self):
        """If lock fails, no side effects should occur."""
        store = LockedResumeStore(orphaned_count=3)

        with pytest.raises(ResumeLockError):
            resume_run(store, "run-001")

        # orphans_marked_for should remain None (never called)
        assert store.orphans_marked_for is None


# --- Tests for no checkpoint found (restart from beginning) ---


class TestNoCheckpointRestart:
    """Tests for resume when no checkpoint exists."""

    def test_no_checkpoint_returns_resume_from_beginning(self):
        """When no checkpoint exists, pipeline starts from ingest."""
        store = InMemoryResumeStore(checkpoint=None)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeFromBeginning)
        assert result.next_node == "ingest"

    def test_no_checkpoint_still_acquires_lock(self):
        """Lock is acquired even when no checkpoint exists."""
        store = InMemoryResumeStore(checkpoint=None)

        resume_run(store, "run-001")

        assert store.lock_acquired_for == "run-001"


# --- Tests for correct next node via routing ---


class TestNextNodeRouting:
    """Tests for routing-based next node determination."""

    def test_route_to_queue_with_escalate_bucket_routes_to_human_review(self):
        """When route_to_queue completed with non-empty escalate bucket, next is human_review."""
        state = _make_checkpoint_state("route_to_queue")
        state["queue_buckets"] = QueueBuckets(
            auto_approve=[],
            escalate=["claim-1", "claim-2"],
            auto_reject=[],
        )
        checkpoint = {
            "step_name": "route_to_queue",
            "step_order": 8,
            "output_state": serialize_state(state),
            "status": "completed",
        }
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "human_review"

    def test_route_to_queue_with_empty_escalate_routes_to_finalize(self):
        """When route_to_queue completed with empty escalate bucket, next is finalize."""
        state = _make_checkpoint_state("route_to_queue")
        state["queue_buckets"] = QueueBuckets(
            auto_approve=["claim-1"],
            escalate=[],
            auto_reject=[],
        )
        checkpoint = {
            "step_name": "route_to_queue",
            "step_order": 8,
            "output_state": serialize_state(state),
            "status": "completed",
        }
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "finalize"

    def test_human_review_completed_routes_to_finalize(self):
        """After human_review completes, next node is finalize."""
        state = _make_checkpoint_state("human_review")
        checkpoint = {
            "step_name": "human_review",
            "step_order": 9,
            "output_state": serialize_state(state),
            "status": "completed",
        }
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "finalize"

    def test_match_rules_completed_routes_to_score_confidence(self):
        """After match_rules completes, next node is score_confidence."""
        checkpoint = _make_checkpoint_dict("match_rules", step_order=6)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "score_confidence"

    def test_extract_claims_completed_routes_to_match_rules(self):
        """After extract_claims completes, next node is match_rules."""
        checkpoint = _make_checkpoint_dict("extract_claims", step_order=5)
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "match_rules"

    def test_finalize_completed_routes_to_end(self):
        """After finalize completes, routing returns end marker."""
        state = _make_checkpoint_state("finalize")
        checkpoint = {
            "step_name": "finalize",
            "step_order": 10,
            "output_state": serialize_state(state),
            "status": "completed",
        }
        store = InMemoryResumeStore(checkpoint=checkpoint)

        result = resume_run(store, "run-001")

        assert isinstance(result, ResumeResult)
        assert result.next_node == "__end__"
