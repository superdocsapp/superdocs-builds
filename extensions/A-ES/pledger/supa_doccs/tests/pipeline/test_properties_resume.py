"""Property-based tests for resume restart correctness.

Uses Hypothesis to verify that resume_run correctly identifies the last
checkpoint, restores valid PipelineState, and determines the correct next
node via the routing function for any valid checkpoint state.

**Validates: Requirements 6.3, 6.8**
"""

from typing import Any, Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.config import load_config
from src.pipeline.resume import (
    NODE_ORDER,
    ResumeResult,
    ResumeStore,
    _resolve_next_node,
    resume_run,
)
from src.pipeline.routing import make_routing_fn
from src.pipeline.serialization import serialize_state
from src.pipeline.state import (
    PipelineConfig,
    PipelineState,
    QueueBuckets,
    SkippedNodeEntry,
    create_initial_state,
)


# --- In-memory ResumeStore for property tests ---


class PropertyResumeStore:
    """In-memory ResumeStore that returns a preconfigured checkpoint."""

    def __init__(self, checkpoint: Optional[dict[str, Any]] = None) -> None:
        self._checkpoint = checkpoint

    def get_last_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        return self._checkpoint

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        return 0

    def acquire_run_lock(self, run_id: str) -> bool:
        return True


# --- Nodes that can appear as valid checkpoints (completed status) ---

# All nodes can be checkpointed when completed
CHECKPOINTABLE_NODES = NODE_ORDER.copy()

# Nodes that support "skipped" status as a valid checkpoint
SKIP_SUPPORTING_NODES = ["extract_text", "chunk"]


# --- Strategies ---


@st.composite
def pipeline_config_strategy(draw: st.DrawFn) -> PipelineConfig:
    """Generate valid PipelineConfig with varied max_retries."""
    max_retries = draw(st.integers(min_value=1, max_value=10))
    return load_config({"max_retries": max_retries})


@st.composite
def completed_checkpoint_state(draw: st.DrawFn) -> tuple[str, PipelineState]:
    """Generate a (node_name, PipelineState) pair for a completed checkpoint.

    The state has node_status='completed' and fields set appropriately
    for the given node to produce a valid routing decision.
    """
    node_name = draw(st.sampled_from(CHECKPOINTABLE_NODES))
    config = draw(pipeline_config_strategy())

    state = create_initial_state(
        run_id=draw(st.uuids().map(str)),
        document_id=draw(st.uuids().map(str)),
        document_version_id=draw(st.uuids().map(str)),
        config=config,
    )

    state["current_node"] = node_name
    state["node_status"] = "completed"
    state["completed_nodes"] = [node_name]

    # For route_to_queue, we need queue_buckets to be set for routing
    if node_name == "route_to_queue":
        # Generate either empty or non-empty escalate bucket
        escalate_items = draw(
            st.lists(st.uuids().map(str), min_size=0, max_size=3)
        )
        state["queue_buckets"] = QueueBuckets(
            auto_approve=draw(
                st.lists(st.uuids().map(str), min_size=0, max_size=3)
            ),
            escalate=escalate_items,
            auto_reject=draw(
                st.lists(st.uuids().map(str), min_size=0, max_size=3)
            ),
        )

    return (node_name, state)


@st.composite
def skipped_checkpoint_state(draw: st.DrawFn) -> tuple[str, PipelineState]:
    """Generate a (node_name, PipelineState) pair for a skipped checkpoint.

    The state has node_status='skipped' with a valid skip_reason entry.
    """
    node_name = draw(st.sampled_from(SKIP_SUPPORTING_NODES))
    config = draw(pipeline_config_strategy())

    state = create_initial_state(
        run_id=draw(st.uuids().map(str)),
        document_id=draw(st.uuids().map(str)),
        document_version_id=draw(st.uuids().map(str)),
        config=config,
    )

    state["current_node"] = node_name
    state["node_status"] = "skipped"  # type: ignore[typeddict-item]

    # Generate valid skip reason (1-255 chars)
    skip_reason = draw(
        st.text(
            alphabet=st.characters(categories=("L", "N", "P", "Z")),
            min_size=1,
            max_size=255,
        )
    )
    state["skipped_nodes"] = [
        SkippedNodeEntry(node_name=node_name, reason=skip_reason)
    ]
    state["completed_nodes"] = [node_name]

    return (node_name, state)


# ============================================================
# Property 10: Resume Restart Correctness
# Validates: Requirements 6.3, 6.8
# ============================================================


class TestResumeRestartCorrectness:
    """Property 10: Resume Restart Correctness.

    For any valid checkpoint state (node with "completed" or "skipped" status),
    resume_run correctly identifies the last checkpoint, restores the state,
    and determines the correct next node via the routing function.

    **Validates: Requirements 6.3, 6.8**
    """

    @given(data=completed_checkpoint_state())
    @settings(max_examples=200)
    def test_resumed_from_step_matches_checkpoint_node(
        self, data: tuple[str, PipelineState]
    ) -> None:
        """result.resumed_from_step matches the generated checkpoint step_name."""
        node_name, state = data

        checkpoint = {
            "step_name": node_name,
            "step_order": NODE_ORDER.index(node_name) + 1,
            "output_state": serialize_state(state),
            "status": "completed",
        }
        store = PropertyResumeStore(checkpoint=checkpoint)

        result = resume_run(store, state["run_id"])

        assert isinstance(result, ResumeResult)
        assert result.resumed_from_step == node_name

    @given(data=completed_checkpoint_state())
    @settings(max_examples=200)
    def test_next_node_matches_routing_function_output(
        self, data: tuple[str, PipelineState]
    ) -> None:
        """result.next_node matches what make_routing_fn(step_name, config)(state)
        would resolve to via the path maps."""
        node_name, state = data

        checkpoint = {
            "step_name": node_name,
            "step_order": NODE_ORDER.index(node_name) + 1,
            "output_state": serialize_state(state),
            "status": "completed",
        }
        store = PropertyResumeStore(checkpoint=checkpoint)

        result = resume_run(store, state["run_id"])

        assert isinstance(result, ResumeResult)

        # Compute expected next_node independently
        config = state["config"]
        routing_fn = make_routing_fn(node_name, config)
        routing_decision = routing_fn(state)
        expected_next_node = _resolve_next_node(node_name, routing_decision)

        assert result.next_node == expected_next_node, (
            f"For checkpoint at '{node_name}' with routing_decision='{routing_decision}', "
            f"expected next_node='{expected_next_node}' but got '{result.next_node}'"
        )

    @given(data=completed_checkpoint_state())
    @settings(max_examples=200)
    def test_restored_state_is_valid_pipeline_state(
        self, data: tuple[str, PipelineState]
    ) -> None:
        """result.state is a valid PipelineState matching the checkpoint data."""
        node_name, state = data

        checkpoint = {
            "step_name": node_name,
            "step_order": NODE_ORDER.index(node_name) + 1,
            "output_state": serialize_state(state),
            "status": "completed",
        }
        store = PropertyResumeStore(checkpoint=checkpoint)

        result = resume_run(store, state["run_id"])

        assert isinstance(result, ResumeResult)
        # Verify the restored state matches the original checkpoint state
        assert result.state["run_id"] == state["run_id"]
        assert result.state["document_id"] == state["document_id"]
        assert result.state["document_version_id"] == state["document_version_id"]
        assert result.state["current_node"] == state["current_node"]
        assert result.state["node_status"] == state["node_status"]
        assert result.state["config"] == state["config"]
        assert result.state["completed_nodes"] == state["completed_nodes"]

    @given(data=skipped_checkpoint_state())
    @settings(max_examples=100)
    def test_skipped_checkpoint_resumed_from_step_matches(
        self, data: tuple[str, PipelineState]
    ) -> None:
        """Skipped nodes: result.resumed_from_step matches the generated checkpoint step_name."""
        node_name, state = data

        checkpoint = {
            "step_name": node_name,
            "step_order": NODE_ORDER.index(node_name) + 1,
            "output_state": serialize_state(state),
            "status": "skipped",
        }
        store = PropertyResumeStore(checkpoint=checkpoint)

        result = resume_run(store, state["run_id"])

        assert isinstance(result, ResumeResult)
        assert result.resumed_from_step == node_name

    @given(data=skipped_checkpoint_state())
    @settings(max_examples=100)
    def test_skipped_checkpoint_next_node_matches_routing(
        self, data: tuple[str, PipelineState]
    ) -> None:
        """Skipped nodes: result.next_node matches routing function resolution."""
        node_name, state = data

        checkpoint = {
            "step_name": node_name,
            "step_order": NODE_ORDER.index(node_name) + 1,
            "output_state": serialize_state(state),
            "status": "skipped",
        }
        store = PropertyResumeStore(checkpoint=checkpoint)

        result = resume_run(store, state["run_id"])

        assert isinstance(result, ResumeResult)

        # Compute expected next_node independently
        config = state["config"]
        routing_fn = make_routing_fn(node_name, config)
        routing_decision = routing_fn(state)
        expected_next_node = _resolve_next_node(node_name, routing_decision)

        assert result.next_node == expected_next_node, (
            f"For skipped checkpoint at '{node_name}' with "
            f"routing_decision='{routing_decision}', "
            f"expected next_node='{expected_next_node}' but got '{result.next_node}'"
        )

    @given(data=skipped_checkpoint_state())
    @settings(max_examples=100)
    def test_skipped_checkpoint_state_preserves_skip_metadata(
        self, data: tuple[str, PipelineState]
    ) -> None:
        """Skipped nodes: restored state preserves skipped_nodes metadata."""
        node_name, state = data

        checkpoint = {
            "step_name": node_name,
            "step_order": NODE_ORDER.index(node_name) + 1,
            "output_state": serialize_state(state),
            "status": "skipped",
        }
        store = PropertyResumeStore(checkpoint=checkpoint)

        result = resume_run(store, state["run_id"])

        assert isinstance(result, ResumeResult)
        assert result.state["node_status"] == "skipped"
        assert result.state["skipped_nodes"] == state["skipped_nodes"]
        assert len(result.state["skipped_nodes"]) > 0
        assert result.state["skipped_nodes"][0]["node_name"] == node_name
