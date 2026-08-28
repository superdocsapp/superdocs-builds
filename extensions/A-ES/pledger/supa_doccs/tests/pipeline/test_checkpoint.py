"""Tests for the checkpoint persistence layer.

Tests create_step_row and write_checkpoint using an in-memory
CheckpointStore implementation (no real database needed).
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

from src.pipeline.checkpoint import (
    CheckpointStore,
    CheckpointWriteError,
    create_step_row,
    write_checkpoint,
)
from src.pipeline.config import load_config
from src.pipeline.serialization import serialize_state
from src.pipeline.state import PipelineState, QueueBuckets, create_initial_state


# --- In-memory CheckpointStore for testing ---


class InMemoryCheckpointStore:
    """In-memory implementation of CheckpointStore for unit tests."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.checkpoints: list[dict[str, Any]] = []

    def create_step(
        self,
        run_id: str,
        step_name: str,
        step_order: int,
    ) -> None:
        self.steps.append({
            "run_id": run_id,
            "step_name": step_name,
            "step_order": step_order,
            "status": "running",
            "started_at": datetime.now(timezone.utc),
        })

    def write_checkpoint(
        self,
        run_id: str,
        step_name: str,
        step_order: int,
        output_state: dict[str, Any],
        status: str,
        ended_at: datetime,
        **kwargs: Any,
    ) -> None:
        self.checkpoints.append({
            "run_id": run_id,
            "step_name": step_name,
            "step_order": step_order,
            "output_state": output_state,
            "status": status,
            "ended_at": ended_at,
        })


class FailingCheckpointStore:
    """CheckpointStore that always raises on operations."""

    def __init__(self, error_message: str = "DB connection lost") -> None:
        self.error_message = error_message

    def create_step(
        self,
        run_id: str,
        step_name: str,
        step_order: int,
    ) -> None:
        raise RuntimeError(self.error_message)

    def write_checkpoint(
        self,
        run_id: str,
        step_name: str,
        step_order: int,
        output_state: dict[str, Any],
        status: str,
        ended_at: datetime,
        **kwargs: Any,
    ) -> None:
        raise RuntimeError(self.error_message)


# --- Helpers ---


def _make_completed_state(node_name: str = "ingest") -> PipelineState:
    """Create a PipelineState marked as completed for the given node."""
    config = load_config()
    state = create_initial_state(
        run_id="run-001",
        document_id="doc-001",
        document_version_id="ver-001",
        config=config,
    )
    state["current_node"] = node_name
    state["node_status"] = "completed"
    state["completed_nodes"] = [node_name]
    return state


def _make_skipped_state(node_name: str = "extract_text") -> PipelineState:
    """Create a PipelineState marked as skipped for the given node."""
    config = load_config()
    state = create_initial_state(
        run_id="run-002",
        document_id="doc-002",
        document_version_id="ver-002",
        config=config,
    )
    state["current_node"] = node_name
    state["node_status"] = "skipped"
    state["completed_nodes"] = [node_name]
    state["skipped_nodes"] = [{"node_name": node_name, "reason": "input_already_text"}]
    return state


# --- Tests for create_step_row ---


class TestCreateStepRow:
    """Tests for create_step_row function."""

    def test_creates_correct_row(self):
        store = InMemoryCheckpointStore()
        create_step_row(store, run_id="run-001", step_name="ingest", step_order=1)

        assert len(store.steps) == 1
        row = store.steps[0]
        assert row["run_id"] == "run-001"
        assert row["step_name"] == "ingest"
        assert row["step_order"] == 1
        assert row["status"] == "running"
        assert isinstance(row["started_at"], datetime)

    def test_creates_multiple_rows(self):
        store = InMemoryCheckpointStore()
        create_step_row(store, run_id="run-001", step_name="ingest", step_order=1)
        create_step_row(store, run_id="run-001", step_name="extract_text", step_order=2)

        assert len(store.steps) == 2
        assert store.steps[0]["step_name"] == "ingest"
        assert store.steps[1]["step_name"] == "extract_text"
        assert store.steps[0]["step_order"] == 1
        assert store.steps[1]["step_order"] == 2

    def test_failure_raises_checkpoint_write_error(self):
        store = FailingCheckpointStore("connection refused")
        with pytest.raises(CheckpointWriteError, match="Failed to create step row"):
            create_step_row(store, run_id="run-001", step_name="ingest", step_order=1)

    def test_failure_wraps_original_exception(self):
        store = FailingCheckpointStore("timeout")
        with pytest.raises(CheckpointWriteError) as exc_info:
            create_step_row(store, run_id="run-001", step_name="ingest", step_order=1)
        assert exc_info.value.__cause__ is not None
        assert "timeout" in str(exc_info.value.__cause__)


# --- Tests for write_checkpoint ---


class TestWriteCheckpoint:
    """Tests for write_checkpoint function."""

    def test_serializes_state_and_writes_correctly(self):
        store = InMemoryCheckpointStore()
        state = _make_completed_state("ingest")

        write_checkpoint(
            store,
            run_id="run-001",
            step_name="ingest",
            step_order=1,
            state=state,
        )

        assert len(store.checkpoints) == 1
        cp = store.checkpoints[0]
        assert cp["run_id"] == "run-001"
        assert cp["step_name"] == "ingest"
        assert cp["step_order"] == 1
        assert cp["output_state"] == serialize_state(state)
        assert isinstance(cp["ended_at"], datetime)
        assert cp["ended_at"].tzinfo is not None  # timezone-aware

    def test_sets_status_completed_for_completed_node(self):
        store = InMemoryCheckpointStore()
        state = _make_completed_state("ingest")

        write_checkpoint(
            store,
            run_id="run-001",
            step_name="ingest",
            step_order=1,
            state=state,
        )

        assert store.checkpoints[0]["status"] == "completed"

    def test_sets_status_skipped_for_skipped_node(self):
        store = InMemoryCheckpointStore()
        state = _make_skipped_state("extract_text")

        write_checkpoint(
            store,
            run_id="run-002",
            step_name="extract_text",
            step_order=2,
            state=state,
        )

        assert store.checkpoints[0]["status"] == "skipped"

    def test_output_state_is_jsonb_serializable(self):
        """Verify the output_state dict is JSON-native (no bytes, no custom objects)."""
        store = InMemoryCheckpointStore()
        state = _make_completed_state("ingest")
        # Add raw_content bytes to verify serialization handles it
        state["raw_content"] = b"hello world"

        write_checkpoint(
            store,
            run_id="run-001",
            step_name="ingest",
            step_order=1,
            state=state,
        )

        output = store.checkpoints[0]["output_state"]
        # raw_content should be base64 string, not bytes
        assert isinstance(output["raw_content"], str)
        assert output["raw_content"] != b"hello world"

    def test_failure_raises_checkpoint_write_error(self):
        store = FailingCheckpointStore("disk full")
        state = _make_completed_state("ingest")

        with pytest.raises(CheckpointWriteError, match="Failed to write checkpoint"):
            write_checkpoint(
                store,
                run_id="run-001",
                step_name="ingest",
                step_order=1,
                state=state,
            )

    def test_failure_wraps_original_exception(self):
        store = FailingCheckpointStore("serialization error")
        state = _make_completed_state("ingest")

        with pytest.raises(CheckpointWriteError) as exc_info:
            write_checkpoint(
                store,
                run_id="run-001",
                step_name="ingest",
                step_order=1,
                state=state,
            )
        assert exc_info.value.__cause__ is not None
        assert "serialization error" in str(exc_info.value.__cause__)

    def test_ended_at_is_utc(self):
        store = InMemoryCheckpointStore()
        state = _make_completed_state("chunk")

        write_checkpoint(
            store,
            run_id="run-001",
            step_name="chunk",
            step_order=3,
            state=state,
        )

        ended_at = store.checkpoints[0]["ended_at"]
        assert ended_at.tzinfo == timezone.utc

    def test_preserves_full_state_in_output(self):
        """Verify all state keys are present in the serialized output."""
        store = InMemoryCheckpointStore()
        state = _make_completed_state("embed")
        state["embeddings_stored"] = True
        state["chunks"] = [
            {"index": 0, "text": "chunk text", "start_offset": 0, "end_offset": 10}
        ]

        write_checkpoint(
            store,
            run_id="run-001",
            step_name="embed",
            step_order=4,
            state=state,
        )

        output = store.checkpoints[0]["output_state"]
        assert output["run_id"] == "run-001"
        assert output["embeddings_stored"] is True
        assert output["chunks"] == [
            {"index": 0, "text": "chunk text", "start_offset": 0, "end_offset": 10}
        ]
        assert output["node_status"] == "completed"


# --- Tests for status derivation from node_status ---


class TestWriteCheckpointStatusDerivation:
    """Tests verifying status is correctly derived from state['node_status']."""

    def test_completed_node_status_maps_to_completed(self):
        store = InMemoryCheckpointStore()
        state = _make_completed_state("match_rules")

        write_checkpoint(store, "run-001", "match_rules", 6, state)
        assert store.checkpoints[0]["status"] == "completed"

    def test_skipped_node_status_maps_to_skipped(self):
        store = InMemoryCheckpointStore()
        state = _make_skipped_state("chunk")

        write_checkpoint(store, "run-001", "chunk", 3, state)
        assert store.checkpoints[0]["status"] == "skipped"


# --- Tests for failure propagation ---


class TestFailurePropagation:
    """Tests verifying failure propagation behavior."""

    def test_checkpoint_write_error_is_raised_not_swallowed(self):
        """Caller must handle the error (for retry logic)."""
        store = FailingCheckpointStore()
        state = _make_completed_state("ingest")

        with pytest.raises(CheckpointWriteError):
            write_checkpoint(store, "run-001", "ingest", 1, state)

    def test_create_step_error_is_raised_not_swallowed(self):
        """Caller must handle the error (for retry logic)."""
        store = FailingCheckpointStore()

        with pytest.raises(CheckpointWriteError):
            create_step_row(store, "run-001", "ingest", 1)

    def test_checkpoint_write_error_contains_context(self):
        """Error message should include run_id, step_name, step_order."""
        store = FailingCheckpointStore("network partition")
        state = _make_completed_state("score_confidence")

        with pytest.raises(CheckpointWriteError) as exc_info:
            write_checkpoint(store, "run-xyz", "score_confidence", 7, state)

        msg = str(exc_info.value)
        assert "score_confidence" in msg
        assert "run-xyz" in msg
        assert "7" in msg
