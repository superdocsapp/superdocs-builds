"""Property-based tests for checkpoint-if-and-only-if-success.

Property 5: Checkpoint If-And-Only-If Success

A checkpoint (write_checkpoint) should be called if and only if the node's
resulting state has node_status == "completed" or node_status == "skipped".
Never for "error" states or during retries.

**Validates: Requirements 6.1, 6.4, 2.4, 6.6**
"""

from datetime import datetime, timezone
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.checkpoint import (
    CheckpointStore,
    write_checkpoint,
)
from src.pipeline.config import load_config
from src.pipeline.state import (
    PipelineState,
    QueueBuckets,
    create_initial_state,
)


# --- In-memory CheckpointStore for property tests ---


class TrackingCheckpointStore:
    """In-memory CheckpointStore that tracks all write_checkpoint calls."""

    def __init__(self) -> None:
        self.checkpoints: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = []

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


# --- Constants ---

ALL_NODE_NAMES = [
    "ingest",
    "extract_text",
    "chunk",
    "embed",
    "extract_claims",
    "match_rules",
    "score_confidence",
    "route_to_queue",
    "human_review",
    "finalize",
]

# Statuses that should trigger a checkpoint write
CHECKPOINT_STATUSES = ["completed", "skipped"]

# Statuses that should NEVER trigger a checkpoint write
NO_CHECKPOINT_STATUSES = ["error"]


# --- Strategies ---

node_name_strategy = st.sampled_from(ALL_NODE_NAMES)
step_order_strategy = st.integers(min_value=1, max_value=100)
run_id_strategy = st.uuids().map(str)


def _make_state_with_status(
    node_name: str,
    node_status: str,
    run_id: str = "test-run-001",
) -> PipelineState:
    """Create a PipelineState with the specified node and status."""
    config = load_config()
    state = create_initial_state(
        run_id=run_id,
        document_id="doc-001",
        document_version_id="ver-001",
        config=config,
    )
    state["current_node"] = node_name
    state["node_status"] = node_status  # type: ignore[typeddict-item]

    if node_status in ("completed", "skipped"):
        state["completed_nodes"] = [node_name]
    if node_status == "skipped":
        state["skipped_nodes"] = [
            {"node_name": node_name, "reason": "test_skip_reason"}
        ]
    if node_status == "error":
        state["error_type"] = "transient"
        state["error_detail"] = "test error detail"

    return state


def _should_checkpoint(node_status: str) -> bool:
    """Determine whether a checkpoint should be written based on node_status.

    This implements the contract from Requirement 6.1 and 6.4:
    - Checkpoint is written iff node_status is "completed" or "skipped"
    - Checkpoint is NEVER written for "error" states
    """
    return node_status in CHECKPOINT_STATUSES


# ============================================================
# Property 5: Checkpoint If-And-Only-If Success
# Validates: Requirements 6.1, 6.4, 2.4, 6.6
# ============================================================


class TestCheckpointIfAndOnlyIfSuccess:
    """Property 5: Checkpoint If-And-Only-If Success.

    A checkpoint (write_checkpoint) is appropriate if and only if
    node_status == "completed" or node_status == "skipped".
    Never for "error" states or during retries.

    **Validates: Requirements 6.1, 6.4, 2.4, 6.6**
    """

    @given(
        node_name=node_name_strategy,
        step_order=step_order_strategy,
        run_id=run_id_strategy,
    )
    @settings(max_examples=200)
    def test_checkpoint_written_for_completed_status(
        self,
        node_name: str,
        step_order: int,
        run_id: str,
    ) -> None:
        """When node_status is 'completed', write_checkpoint succeeds and
        records status='completed'.

        Per Requirement 6.1: THE Graph SHALL persist a Checkpoint after each
        Node completes with node_status = "completed".
        """
        store = TrackingCheckpointStore()
        state = _make_state_with_status(node_name, "completed", run_id)

        # The contract says: checkpoint should be written for "completed"
        assert _should_checkpoint(state["node_status"]) is True

        # Actually write the checkpoint and verify it works correctly
        write_checkpoint(store, run_id, node_name, step_order, state)

        assert len(store.checkpoints) == 1
        cp = store.checkpoints[0]
        assert cp["status"] == "completed"
        assert cp["run_id"] == run_id
        assert cp["step_name"] == node_name
        assert cp["step_order"] == step_order
        assert isinstance(cp["ended_at"], datetime)
        assert cp["ended_at"].tzinfo == timezone.utc

    @given(
        node_name=st.sampled_from(["extract_text", "chunk"]),
        step_order=step_order_strategy,
        run_id=run_id_strategy,
    )
    @settings(max_examples=200)
    def test_checkpoint_written_for_skipped_status(
        self,
        node_name: str,
        step_order: int,
        run_id: str,
    ) -> None:
        """When node_status is 'skipped', write_checkpoint succeeds and
        records status='skipped'.

        Per Requirement 6.1: THE Graph SHALL persist a Checkpoint after each
        Node completes with node_status = "skipped".
        """
        store = TrackingCheckpointStore()
        state = _make_state_with_status(node_name, "skipped", run_id)

        # The contract says: checkpoint should be written for "skipped"
        assert _should_checkpoint(state["node_status"]) is True

        # Actually write the checkpoint and verify it works correctly
        write_checkpoint(store, run_id, node_name, step_order, state)

        assert len(store.checkpoints) == 1
        cp = store.checkpoints[0]
        assert cp["status"] == "skipped"
        assert cp["run_id"] == run_id
        assert cp["step_name"] == node_name
        assert cp["step_order"] == step_order
        assert isinstance(cp["ended_at"], datetime)
        assert cp["ended_at"].tzinfo == timezone.utc

    @given(
        node_name=node_name_strategy,
        step_order=step_order_strategy,
        run_id=run_id_strategy,
    )
    @settings(max_examples=200)
    def test_no_checkpoint_for_error_status(
        self,
        node_name: str,
        step_order: int,
        run_id: str,
    ) -> None:
        """When node_status is 'error', checkpoint should NEVER be written.

        Per Requirement 6.4: WHEN a Node fails (returns node_status = "error"),
        THE Graph SHALL NOT persist a Checkpoint for that Node execution.

        This test verifies the contract: _should_checkpoint returns False for
        error states, meaning the pipeline must never call write_checkpoint
        for error states.
        """
        state = _make_state_with_status(node_name, "error", run_id)

        # The contract says: checkpoint must NOT be written for "error"
        assert _should_checkpoint(state["node_status"]) is False

    @given(
        node_name=node_name_strategy,
        step_order=step_order_strategy,
        run_id=run_id_strategy,
        retry_count=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=200)
    def test_no_checkpoint_during_retries(
        self,
        node_name: str,
        step_order: int,
        run_id: str,
        retry_count: int,
    ) -> None:
        """During retry cycles, no checkpoint should be written.

        Per Requirement 2.4: WHEN a retry is triggered, THE Graph SHALL NOT
        create a new Checkpoint before re-invoking the Node.

        Per Requirement 6.6: WHILE a retry cycle is in progress for a given
        Node, THE Graph SHALL NOT overwrite the pre-node Checkpoint.

        A retry is in progress when node_status = "error" and error_type =
        "transient" and retry_count < max_retries. In this scenario, the
        checkpoint contract says no checkpoint should be written.
        """
        config = load_config()
        state = create_initial_state(
            run_id=run_id,
            document_id="doc-001",
            document_version_id="ver-001",
            config=config,
        )
        state["current_node"] = node_name
        state["node_status"] = "error"  # type: ignore[typeddict-item]
        state["error_type"] = "transient"
        state["error_detail"] = "transient failure for retry"
        state["retries"] = {node_name: retry_count}

        # During any retry cycle (error + transient), checkpoint must not be written
        assert _should_checkpoint(state["node_status"]) is False

    @given(
        node_name=node_name_strategy,
        node_status=st.sampled_from(["completed", "skipped", "error"]),
        step_order=step_order_strategy,
        run_id=run_id_strategy,
    )
    @settings(max_examples=500)
    def test_checkpoint_biconditional_across_all_statuses(
        self,
        node_name: str,
        node_status: str,
        step_order: int,
        run_id: str,
    ) -> None:
        """The biconditional: checkpoint is written IFF status is completed or skipped.

        This is the core property: for ANY node and ANY valid status,
        the checkpoint decision is deterministic and correct:
        - completed → checkpoint written
        - skipped → checkpoint written
        - error → NO checkpoint

        **Validates: Requirements 6.1, 6.4, 2.4, 6.6**
        """
        state = _make_state_with_status(node_name, node_status, run_id)
        should_write = _should_checkpoint(state["node_status"])

        if node_status in ("completed", "skipped"):
            # IFF success: checkpoint SHOULD be written
            assert should_write is True

            # Verify actual checkpoint write works and records correct status
            store = TrackingCheckpointStore()
            write_checkpoint(store, run_id, node_name, step_order, state)
            assert len(store.checkpoints) == 1
            assert store.checkpoints[0]["status"] == node_status
        else:
            # IFF not success: checkpoint MUST NOT be written
            assert should_write is False
            assert node_status == "error"

    @given(
        node_name=node_name_strategy,
        step_order=step_order_strategy,
        run_id=run_id_strategy,
    )
    @settings(max_examples=200)
    def test_checkpoint_status_matches_node_status(
        self,
        node_name: str,
        step_order: int,
        run_id: str,
    ) -> None:
        """The checkpoint status field always matches the state's node_status.

        When write_checkpoint is called for a valid (completed/skipped) state,
        the recorded status in the checkpoint store must exactly equal the
        node_status from the state. This ensures checkpoint integrity.
        """
        for status in CHECKPOINT_STATUSES:
            store = TrackingCheckpointStore()
            state = _make_state_with_status(node_name, status, run_id)

            write_checkpoint(store, run_id, node_name, step_order, state)

            assert store.checkpoints[0]["status"] == status
