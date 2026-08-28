"""Routing function factory for the LangGraph pipeline.

Each conditional edge in the pipeline graph uses a routing function that
inspects the current PipelineState and returns a string literal determining
the next node to execute. The make_routing_fn factory creates the appropriate
routing function for each source node.

Requirements: 1.6, 1.7, 2.1, 2.2, 2.5, 11.3, 11.4
"""

from collections.abc import Callable

from src.pipeline.state import PipelineConfig, PipelineState


def make_routing_fn(
    node_name: str, config: PipelineConfig
) -> Callable[[PipelineState], str]:
    """Factory that creates a routing function for a given source node.

    The returned function inspects PipelineState and returns one of:
    - "next": advance to the next node in sequence
    - "retry": re-invoke the same node (transient error, retries available)
    - "escalate": route to route_to_queue for human triage
    - "finalize": proceed to finalize node (from human_review)
    - "end": pipeline complete (from finalize on success)

    Special per-node logic:
    - ingest: no retry support; any error → escalate
    - classify_document: on completed + unclassified → escalate; otherwise next; retries on transient error
    - chunk: no retry support; completed/skipped → next; errors → escalate
    - route_to_queue: on completed, checks escalate bucket to decide next
    - human_review: always returns "finalize" on completed
    - finalize: returns "end" on completed; retry/escalate on error

    Args:
        node_name: The name of the source node this routing function serves.
        config: Frozen pipeline configuration containing max_retries.

    Returns:
        A routing function that takes PipelineState and returns a decision string.
    """
    max_retries = config["max_retries"]

    # Dispatch to node-specific routing logic
    if node_name == "ingest":
        return _make_ingest_route()
    elif node_name == "classify_document":
        return _make_classify_document_route(max_retries)
    elif node_name == "route_to_queue":
        return _make_route_to_queue_route(max_retries)
    elif node_name == "human_review":
        return _make_human_review_route()
    elif node_name == "finalize":
        return _make_finalize_route(max_retries)
    elif node_name == "chunk":
        return _make_chunk_route()
    else:
        # General case: extract_text, embed, extract_claims, match_rules, score_confidence
        return _make_general_route(node_name, max_retries)


def _is_valid_skip_reason(state: PipelineState, node_name: str) -> bool:
    """Validate skip_reason per Requirement 3.5.

    Returns True if the last entry in skipped_nodes for the given node
    has a non-empty reason of 1-255 characters. Returns False (triggering
    escalation) if:
    - skipped_nodes is empty
    - No entry matches the node_name
    - The reason is None, empty string, or exceeds 255 characters
    """
    skipped_nodes = state.get("skipped_nodes", [])
    if not skipped_nodes:
        return False

    # Find the last entry for this node
    matching_entry = None
    for entry in skipped_nodes:
        if entry["node_name"] == node_name:
            matching_entry = entry

    if matching_entry is None:
        return False

    reason = matching_entry.get("reason")
    if reason is None or reason == "" or len(reason) > 255:
        return False

    return True


def _make_ingest_route() -> Callable[[PipelineState], str]:
    """Ingest routing: next on completed, escalate on any error.

    Ingest does not support retry or skip — any error is permanent escalation.
    """

    def route(state: PipelineState) -> str:
        status = state["node_status"]

        if status == "completed":
            return "next"
        elif status == "error":
            return "escalate"
        else:
            # Unhandled state — treat as permanent error (Req 1.7)
            return "escalate"

    return route


def _make_classify_document_route(
    max_retries: int,
) -> Callable[[PipelineState], str]:
    """Classify document routing: next, escalate, or retry.

    On completed:
    - If classification_label == "unclassified" → "escalate" (route to approval queue)
    - Otherwise → "next" (proceed to chunk)

    On error:
    - Transient error below max → "retry"
    - Transient error at/above max → "escalate"
    - Permanent error → "escalate"

    Requirements: 1.1, 1.2
    """

    def route(state: PipelineState) -> str:
        status = state["node_status"]

        if status == "completed":
            classification_label = state.get("classification_label")  # type: ignore[call-overload]
            if classification_label == "unclassified":
                return "escalate"
            return "next"
        elif status == "error":
            error_type = state.get("error_type")
            retries = state["retries"].get("classify_document", 0)
            if error_type == "transient" and retries < max_retries:
                return "retry"
            else:
                return "escalate"
        else:
            # Unhandled state — treat as permanent error (Req 1.7)
            return "escalate"

    return route


def _make_chunk_route() -> Callable[[PipelineState], str]:
    """Chunk routing: next on completed/skipped, escalate on any error.

    Chunk does not support retry — errors are permanent.
    Per Req 3.5: validates skip_reason when status is "skipped".
    """

    def route(state: PipelineState) -> str:
        status = state["node_status"]

        if status == "completed":
            return "next"
        elif status == "skipped":
            if not _is_valid_skip_reason(state, "chunk"):
                return "escalate"
            return "next"
        elif status == "error":
            return "escalate"
        else:
            # Unhandled state — treat as permanent error (Req 1.7)
            return "escalate"

    return route


def _make_route_to_queue_route(
    max_retries: int,
) -> Callable[[PipelineState], str]:
    """Route-to-queue routing: checks escalate bucket on completed.

    On completed:
    - If queue_buckets["escalate"] is non-empty → "escalate" (to human_review)
    - If queue_buckets["escalate"] is empty → "next" (to finalize)

    On error: standard transient retry logic.
    """

    def route(state: PipelineState) -> str:
        status = state["node_status"]

        if status == "completed":
            escalate_bucket = state["queue_buckets"]["escalate"]
            if len(escalate_bucket) > 0:
                return "escalate"
            else:
                return "next"
        elif status == "error":
            error_type = state.get("error_type")
            retries = state["retries"].get("route_to_queue", 0)
            if error_type == "transient" and retries < max_retries:
                return "retry"
            else:
                return "escalate"
        else:
            # Unhandled state — treat as permanent error (Req 1.7)
            return "escalate"

    return route


def _make_human_review_route() -> Callable[[PipelineState], str]:
    """Human review routing: always returns 'finalize' on completed.

    After human review completes (all decisions received), proceed to finalize.
    """

    def route(state: PipelineState) -> str:
        status = state["node_status"]

        if status == "completed":
            return "finalize"
        else:
            # Unhandled state — treat as permanent error (Req 1.7)
            return "escalate"

    return route


def _make_finalize_route(max_retries: int) -> Callable[[PipelineState], str]:
    """Finalize routing: end on completed, retry/escalate on transient error.

    On completed → "end" (pipeline terminates successfully).
    On transient error below max → "retry".
    On transient error at/above max → "escalate" (FAILED terminal state).
    """

    def route(state: PipelineState) -> str:
        status = state["node_status"]

        if status == "completed":
            return "end"
        elif status == "error":
            error_type = state.get("error_type")
            retries = state["retries"].get("finalize", 0)
            if error_type == "transient" and retries < max_retries:
                return "retry"
            else:
                return "escalate"
        else:
            # Unhandled state — treat as permanent error (Req 1.7)
            return "escalate"

    return route


def _make_general_route(
    node_name: str, max_retries: int
) -> Callable[[PipelineState], str]:
    """General routing for nodes with standard next/retry/escalate logic.

    Covers: extract_text, embed, extract_claims, match_rules, score_confidence.

    On completed → "next"
    On skipped → "next" (with skip_reason validation per Req 3.5)
    On transient error below max → "retry"
    On transient error at/above max → "escalate"
    On permanent error → "escalate"
    On unhandled state → "escalate" (Req 1.7)
    """

    def route(state: PipelineState) -> str:
        status = state["node_status"]

        if status == "completed":
            return "next"
        elif status == "skipped":
            if not _is_valid_skip_reason(state, node_name):
                return "escalate"
            return "next"
        elif status == "error":
            error_type = state.get("error_type")
            retries = state["retries"].get(node_name, 0)
            if error_type == "transient" and retries < max_retries:
                return "retry"
            else:
                # permanent error, or transient at max retries → escalate
                return "escalate"
        else:
            # Unhandled state — treat as permanent error (Req 1.7)
            return "escalate"

    return route
