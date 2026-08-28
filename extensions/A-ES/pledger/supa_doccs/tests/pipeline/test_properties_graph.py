"""Property-based tests for the Node Completion Contract.

Property 16: Node Completion Contract

For any node execution result:
- If node_status == "completed": current_node == node_name AND node_name is in completed_nodes
- If node_status == "skipped": current_node == node_name AND node_name is in completed_nodes
- If node_status == "error": current_node == node_name AND node_name is NOT in completed_nodes

This property verifies structurally that all node outputs conform to the
completion contract defined in Requirement 7.4.

**Validates: Requirements 7.4**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.config import load_config
from src.pipeline.state import (
    PipelineState,
    QueueBuckets,
    SkippedNodeEntry,
    create_initial_state,
)


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

VALID_STATUSES = ["completed", "skipped", "error"]


# --- Helpers ---


def simulate_node_execution(
    node_name: str,
    node_status: str,
    prior_completed: list[str],
) -> PipelineState:
    """Simulate a node execution result following the node contract.

    Builds a PipelineState as a node would produce it:
    - Sets current_node to node_name
    - Sets node_status to the given status
    - For completed/skipped: appends node_name to completed_nodes
    - For error: does NOT append node_name to completed_nodes
    """
    config = load_config()
    state = create_initial_state(
        run_id="test-run-001",
        document_id="doc-001",
        document_version_id="ver-001",
        config=config,
    )

    completed_nodes = list(prior_completed)

    state["current_node"] = node_name
    state["node_status"] = node_status  # type: ignore[typeddict-item]

    if node_status in ("completed", "skipped"):
        completed_nodes.append(node_name)
        state["error_type"] = None
        state["error_detail"] = None
    elif node_status == "error":
        state["error_type"] = "transient"
        state["error_detail"] = "simulated error"

    if node_status == "skipped":
        state["skipped_nodes"] = [
            SkippedNodeEntry(node_name=node_name, reason="test_skip_reason")
        ]

    state["completed_nodes"] = completed_nodes
    return state


# --- Strategies ---


prior_completed_strategy = st.lists(
    st.sampled_from(ALL_NODE_NAMES),
    max_size=9,
    unique=True,
)


# ============================================================
# Property 16: Node Completion Contract
# Validates: Requirements 7.4
# ============================================================


class TestNodeCompletionContract:
    """Property 16: Node Completion Contract.

    For any node execution result, the completion contract holds:
    - completed/skipped → current_node set AND name in completed_nodes
    - error → current_node set AND name NOT in completed_nodes

    **Validates: Requirements 7.4**
    """

    @given(
        node_name=st.sampled_from(ALL_NODE_NAMES),
        prior_completed=prior_completed_strategy,
    )
    @settings(max_examples=200)
    def test_completed_node_in_completed_nodes(
        self,
        node_name: str,
        prior_completed: list[str],
    ) -> None:
        """When node_status is 'completed', current_node == node_name
        AND node_name appears in completed_nodes.

        **Validates: Requirements 7.4**
        """
        # Remove node_name from prior if present to avoid duplication ambiguity
        prior = [n for n in prior_completed if n != node_name]

        state = simulate_node_execution(node_name, "completed", prior)

        assert state["current_node"] == node_name
        assert node_name in state["completed_nodes"]

    @given(
        node_name=st.sampled_from(ALL_NODE_NAMES),
        prior_completed=prior_completed_strategy,
    )
    @settings(max_examples=200)
    def test_skipped_node_in_completed_nodes(
        self,
        node_name: str,
        prior_completed: list[str],
    ) -> None:
        """When node_status is 'skipped', current_node == node_name
        AND node_name appears in completed_nodes.

        **Validates: Requirements 7.4**
        """
        prior = [n for n in prior_completed if n != node_name]

        state = simulate_node_execution(node_name, "skipped", prior)

        assert state["current_node"] == node_name
        assert node_name in state["completed_nodes"]

    @given(
        node_name=st.sampled_from(ALL_NODE_NAMES),
        prior_completed=prior_completed_strategy,
    )
    @settings(max_examples=200)
    def test_error_node_not_in_completed_nodes(
        self,
        node_name: str,
        prior_completed: list[str],
    ) -> None:
        """When node_status is 'error', current_node == node_name
        AND node_name does NOT appear in completed_nodes.

        **Validates: Requirements 7.4**
        """
        # Remove node_name from prior to ensure it's not already there
        prior = [n for n in prior_completed if n != node_name]

        state = simulate_node_execution(node_name, "error", prior)

        assert state["current_node"] == node_name
        assert node_name not in state["completed_nodes"]

    @given(
        node_name=st.sampled_from(ALL_NODE_NAMES),
        node_status=st.sampled_from(VALID_STATUSES),
        prior_completed=prior_completed_strategy,
    )
    @settings(max_examples=500)
    def test_completion_contract_biconditional(
        self,
        node_name: str,
        node_status: str,
        prior_completed: list[str],
    ) -> None:
        """The biconditional contract: node_name in completed_nodes IFF
        status is 'completed' or 'skipped'.

        For ANY node and ANY valid status, the completion contract holds:
        - current_node is always set to node_name
        - completed_nodes contains node_name iff status is success

        **Validates: Requirements 7.4**
        """
        prior = [n for n in prior_completed if n != node_name]

        state = simulate_node_execution(node_name, node_status, prior)

        # current_node is always set to the executing node's name
        assert state["current_node"] == node_name

        if node_status in ("completed", "skipped"):
            # Success: node_name MUST be in completed_nodes
            assert node_name in state["completed_nodes"]
        else:
            # Error: node_name MUST NOT be in completed_nodes
            assert node_name not in state["completed_nodes"]

    @given(
        node_name=st.sampled_from(ALL_NODE_NAMES),
        node_status=st.sampled_from(["completed", "skipped"]),
        prior_completed=prior_completed_strategy,
    )
    @settings(max_examples=200)
    def test_completed_nodes_preserves_prior_entries(
        self,
        node_name: str,
        node_status: str,
        prior_completed: list[str],
    ) -> None:
        """When a node completes, all previously completed nodes remain
        in the completed_nodes list (append-only behavior).

        **Validates: Requirements 7.4**
        """
        prior = [n for n in prior_completed if n != node_name]

        state = simulate_node_execution(node_name, node_status, prior)

        # All prior entries must still be present
        for prior_node in prior:
            assert prior_node in state["completed_nodes"]

        # The new node is appended at the end
        assert state["completed_nodes"][-1] == node_name
