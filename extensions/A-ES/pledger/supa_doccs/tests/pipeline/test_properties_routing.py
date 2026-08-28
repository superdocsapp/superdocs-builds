"""Property-based tests for routing functions.

Uses Hypothesis to generate varied inputs and verify routing invariants
hold across all valid (and invalid) state configurations.
"""

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.pipeline.config import load_config
from src.pipeline.routing import make_routing_fn
from src.pipeline.state import (
    PipelineConfig,
    PipelineState,
    QueueBuckets,
    SkippedNodeEntry,
    create_initial_state,
)

# --- Constants ---

ALL_NODE_NAMES = [
    "ingest",
    "extract_text",
    "classify_document",
    "chunk",
    "embed",
    "extract_claims",
    "match_rules",
    "score_confidence",
    "route_to_queue",
    "human_review",
    "finalize",
]

# Valid decisions per source node
VALID_DECISIONS: dict[str, set[str]] = {
    "ingest": {"next", "escalate"},
    "extract_text": {"next", "retry", "escalate"},
    "classify_document": {"next", "retry", "escalate"},
    "chunk": {"next", "escalate"},
    "embed": {"next", "retry", "escalate"},
    "extract_claims": {"next", "retry", "escalate"},
    "match_rules": {"next", "retry", "escalate"},
    "score_confidence": {"next", "retry", "escalate"},
    "route_to_queue": {"next", "retry", "escalate"},
    "human_review": {"finalize", "escalate"},
    "finalize": {"end", "retry", "escalate"},
}

# Nodes that support retry (transient error → retry when below max_retries)
RETRYABLE_NODES = [
    "extract_text",
    "classify_document",
    "embed",
    "extract_claims",
    "match_rules",
    "score_confidence",
    "route_to_queue",
    "finalize",
]


# --- Helpers ---


def _make_state_with_skip(
    node_name: str,
    skip_reason: str | None,
    include_skipped_entry: bool = True,
) -> PipelineState:
    """Create a PipelineState with node_status='skipped' and optional skipped_nodes entry.

    Args:
        node_name: The node that was skipped.
        skip_reason: The reason string (can be None, empty, or any length).
        include_skipped_entry: Whether to include the node in skipped_nodes list.
    """
    cfg = load_config()
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=cfg,
    )
    state["node_status"] = "skipped"  # type: ignore[typeddict-item]

    if include_skipped_entry:
        entry: SkippedNodeEntry = {
            "node_name": node_name,
            "reason": skip_reason,  # type: ignore[typeddict-item]
        }
        state["skipped_nodes"] = [entry]
    else:
        state["skipped_nodes"] = []

    return state


# --- Strategy for valid skip reasons (1 to 255 chars, non-empty) ---

valid_skip_reason_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=255,
)

# --- Strategy for invalid skip reasons ---

# Empty string
empty_reason_strategy = st.just("")

# Exceeds 255 characters
too_long_reason_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S", "Z")),
    min_size=256,
    max_size=500,
)

# Nodes that support skip logic
SKIP_SUPPORTING_NODES = ["extract_text", "chunk"]


# ============================================================
# Property 7: Skip Routing and Metadata
# Validates: Requirements 3.1, 3.4, 3.5
# ============================================================


class TestSkipRoutingProperty:
    """Property 7: Skip Routing and Metadata.

    Per Requirement 3.5: IF a Node returns node_status = 'skipped' with
    skip_reason that is null, empty, or exceeds 255 characters, THEN THE
    Routing_Function SHALL treat the result as an error and return escalate.

    Per Requirement 3.1: WHEN a Node returns node_status = 'skipped' with
    a valid skip_reason (1-255 chars, non-empty), THE Routing_Function SHALL
    return 'next'.

    **Validates: Requirements 3.1, 3.4, 3.5**
    """

    @given(
        node_name=st.sampled_from(SKIP_SUPPORTING_NODES),
        skip_reason=valid_skip_reason_strategy,
    )
    @settings(max_examples=100)
    def test_valid_skip_reason_routes_next(
        self, node_name: str, skip_reason: str
    ) -> None:
        """Valid skip_reason (1-255 chars, non-empty) → routing returns 'next'."""
        config = load_config()
        route = make_routing_fn(node_name, config)
        state = _make_state_with_skip(node_name, skip_reason)
        assert route(state) == "next"

    @given(
        node_name=st.sampled_from(SKIP_SUPPORTING_NODES),
        skip_reason=too_long_reason_strategy,
    )
    @settings(max_examples=100)
    def test_too_long_skip_reason_routes_escalate(
        self, node_name: str, skip_reason: str
    ) -> None:
        """skip_reason exceeding 255 characters → routing returns 'escalate'."""
        assume(len(skip_reason) > 255)
        config = load_config()
        route = make_routing_fn(node_name, config)
        state = _make_state_with_skip(node_name, skip_reason)
        assert route(state) == "escalate"

    @given(node_name=st.sampled_from(SKIP_SUPPORTING_NODES))
    @settings(max_examples=50)
    def test_empty_skip_reason_routes_escalate(self, node_name: str) -> None:
        """Empty string skip_reason → routing returns 'escalate'."""
        config = load_config()
        route = make_routing_fn(node_name, config)
        state = _make_state_with_skip(node_name, "")
        assert route(state) == "escalate"

    @given(node_name=st.sampled_from(SKIP_SUPPORTING_NODES))
    @settings(max_examples=50)
    def test_missing_skipped_nodes_entry_routes_escalate(
        self, node_name: str
    ) -> None:
        """Missing skipped_nodes entry when status is 'skipped' → routing returns 'escalate'."""
        config = load_config()
        route = make_routing_fn(node_name, config)
        state = _make_state_with_skip(
            node_name, "some_reason", include_skipped_entry=False
        )
        assert route(state) == "escalate"

    @given(node_name=st.sampled_from(SKIP_SUPPORTING_NODES))
    @settings(max_examples=50)
    def test_none_skip_reason_routes_escalate(self, node_name: str) -> None:
        """None (null) skip_reason → routing returns 'escalate'."""
        config = load_config()
        route = make_routing_fn(node_name, config)
        state = _make_state_with_skip(node_name, None)  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# Property 3: Retry Routing Correctness
# Validates: Requirements 2.1, 2.2
# ============================================================


@given(
    node_name=st.sampled_from(RETRYABLE_NODES),
    max_retries=st.integers(min_value=1, max_value=10),
    retry_count=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=500)
def test_retry_routing_correctness(
    node_name: str,
    max_retries: int,
    retry_count: int,
) -> None:
    """Property 3: Retry Routing Correctness.

    **Validates: Requirements 2.1, 2.2**

    For any node that supports retry (extract_text, embed, extract_claims,
    match_rules, score_confidence, route_to_queue, finalize) and any retry count:
    - If retries[node_name] < config["max_retries"], routing returns "retry"
    - If retries[node_name] >= config["max_retries"], routing returns "escalate"
    """
    config: PipelineConfig = load_config({"max_retries": max_retries})
    route = make_routing_fn(node_name, config)

    state = create_initial_state(
        run_id="test-run",
        document_id="test-doc",
        document_version_id="test-version",
        config=config,
    )
    state["node_status"] = "error"  # type: ignore[typeddict-item]
    state["error_type"] = "transient"  # type: ignore[typeddict-item]
    state["retries"] = {node_name: retry_count}

    result = route(state)

    if retry_count < max_retries:
        assert result == "retry", (
            f"Expected 'retry' for {node_name} with "
            f"retries={retry_count} < max_retries={max_retries}, "
            f"got '{result}'"
        )
    else:
        assert result == "escalate", (
            f"Expected 'escalate' for {node_name} with "
            f"retries={retry_count} >= max_retries={max_retries}, "
            f"got '{result}'"
        )

# ============================================================
# Property 2: Routing Determinism — Exactly One Match
# Validates: Requirements 11.4, 1.7
# ============================================================

# Arbitrary node_status: valid literals plus random strings for unhandled states
_node_status_strategy = st.one_of(
    st.sampled_from(["completed", "skipped", "error"]),
    st.text(min_size=1, max_size=20),
)

# Arbitrary error_type: valid literals, None, and random strings
_error_type_strategy = st.one_of(
    st.none(),
    st.sampled_from(["transient", "permanent"]),
    st.text(min_size=1, max_size=20),
)

# Arbitrary retry counts: 0 to 100
_retry_count_strategy = st.integers(min_value=0, max_value=100)

# Arbitrary queue_buckets with empty and non-empty escalate lists
_queue_buckets_strategy = st.fixed_dictionaries(
    {
        "auto_approve": st.lists(st.uuids().map(str), max_size=5),
        "escalate": st.lists(st.uuids().map(str), max_size=5),
        "auto_reject": st.lists(st.uuids().map(str), max_size=5),
    }
)


@st.composite
def arbitrary_routing_state(draw: st.DrawFn) -> PipelineState:
    """Generate arbitrary PipelineState values that exercise routing logic.

    Focuses on the fields that routing functions inspect:
    - node_status (including invalid/unhandled values)
    - error_type (including None and invalid values)
    - retries dict (with varying counts per node, 0 to 100)
    - queue_buckets (with empty and non-empty escalate lists)
    """
    config = load_config()

    state = create_initial_state(
        run_id=draw(st.uuids().map(str)),
        document_id=draw(st.uuids().map(str)),
        document_version_id=draw(st.uuids().map(str)),
        config=config,
    )

    # Override routing-relevant fields with arbitrary values
    state["node_status"] = draw(_node_status_strategy)  # type: ignore[typeddict-item]
    state["error_type"] = draw(_error_type_strategy)  # type: ignore[typeddict-item]
    state["retries"] = draw(
        st.dictionaries(
            keys=st.sampled_from(ALL_NODE_NAMES),
            values=_retry_count_strategy,
            max_size=10,
        )
    )
    state["queue_buckets"] = draw(_queue_buckets_strategy)  # type: ignore[typeddict-item]

    return state


@given(state=arbitrary_routing_state(), node_name=st.sampled_from(ALL_NODE_NAMES))
@settings(max_examples=500)
def test_routing_determinism_exactly_one_match(
    state: PipelineState, node_name: str
) -> None:
    """Property 2: Routing Determinism — Exactly One Match.

    **Validates: Requirements 11.4, 1.7**

    For any State produced by any source node:
    1. make_routing_fn(node_name, config)(state) does not raise
    2. The result is in the set of valid decisions for that node
    3. The function is deterministic (same input always gives same output)
    """
    config = state["config"]
    routing_fn = make_routing_fn(node_name, config)

    # 1. The routing function must not raise an exception
    result = routing_fn(state)

    # 2. The result must be one of the valid decisions for this node
    valid = VALID_DECISIONS[node_name]
    assert result in valid, (
        f"Routing for '{node_name}' returned '{result}' "
        f"which is not in valid decisions {valid}. "
        f"State: node_status={state['node_status']!r}, "
        f"error_type={state.get('error_type')!r}, "
        f"retries={state['retries']}"
    )

    # 3. Determinism: calling again with the same state gives the same result
    result_again = routing_fn(state)
    assert result == result_again, (
        f"Routing for '{node_name}' is non-deterministic: "
        f"first call returned '{result}', second call returned '{result_again}'"
    )
