"""Resume logic for kill-and-resume pipeline execution.

Provides resume_run() which restores pipeline State from the last checkpoint,
marks orphaned "running" rows as failed, acquires an exclusive advisory lock
to enforce single-writer semantics, and determines the next node to execute.

Requirements: 6.3, 6.8
"""

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from src.pipeline.routing import make_routing_fn
from src.pipeline.serialization import deserialize_state
from src.pipeline.state import PipelineState


# --- Node ordering for determining "next" node ---

NODE_ORDER: list[str] = [
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


# --- Protocol for dependency injection ---


class ResumeStore(Protocol):
    """Abstract protocol for resume persistence operations.

    Implementations back onto SQLAlchemy sessions (production) or
    in-memory stores (testing).
    """

    def get_last_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        """Query highest step_order with completed/skipped status.

        Returns dict with step_name, step_order, output_state, status or None
        if no checkpoint exists.
        """
        ...

    def mark_orphaned_running_as_failed(self, run_id: str) -> int:
        """Mark any run_steps with status 'running' and ended_at NULL as 'failed'.

        Sets error_details to 'interrupted'. Returns count of rows updated.
        """
        ...

    def acquire_run_lock(self, run_id: str) -> bool:
        """Try to acquire exclusive advisory lock on run_id.

        Returns True if acquired, False if already held by another session.
        """
        ...


# --- Result types ---


class ResumeLockError(Exception):
    """Raised when the exclusive advisory lock cannot be acquired."""

    pass


@dataclass
class ResumeResult:
    """Result of a successful resume_run call.

    Attributes:
        state: The deserialized PipelineState from the last checkpoint.
        next_node: The name of the next node to execute.
        resumed_from_step: The step_name of the checkpoint used for restore.
        orphaned_count: Number of orphaned 'running' rows marked as failed.
    """

    state: PipelineState
    next_node: str
    resumed_from_step: str
    orphaned_count: int


@dataclass
class ResumeFromBeginning:
    """Result when no checkpoint is found — pipeline starts from the beginning.

    Attributes:
        next_node: Always 'ingest' (the entry point).
        orphaned_count: Number of orphaned 'running' rows marked as failed.
    """

    next_node: str
    orphaned_count: int


def resume_run(
    store: ResumeStore,
    run_id: str,
) -> ResumeResult | ResumeFromBeginning:
    """Resume a pipeline run from the last checkpoint.

    Steps:
    1. Acquire exclusive advisory lock on run_id (fail fast if already held)
    2. Mark orphaned "running" rows as "failed" with error_details="interrupted"
    3. Query highest step_order with completed/skipped status for this run_id
    4. If no checkpoint found → start from beginning (return ResumeFromBeginning)
    5. Load output_state JSONB and deserialize via deserialize_state()
    6. Determine next node by applying the routing function for the last completed node
    7. Return the restored state and the next node name

    Args:
        store: The resume store implementation (dependency injection).
        run_id: UUID string of the run to resume.

    Returns:
        ResumeResult if a checkpoint was found, ResumeFromBeginning otherwise.

    Raises:
        ResumeLockError: If the exclusive advisory lock cannot be acquired
            (another execution is already running for this run_id).
    """
    # 1. Acquire exclusive advisory lock
    if not store.acquire_run_lock(run_id):
        raise ResumeLockError(
            f"Cannot resume run {run_id}: exclusive lock already held "
            f"by another session"
        )

    # 2. Mark orphaned "running" rows as "failed"
    orphaned_count = store.mark_orphaned_running_as_failed(run_id)

    # 3. Query highest completed/skipped checkpoint
    checkpoint = store.get_last_checkpoint(run_id)

    # 4. No checkpoint → start from beginning
    if checkpoint is None:
        return ResumeFromBeginning(
            next_node="ingest",
            orphaned_count=orphaned_count,
        )

    # 5. Deserialize the stored state
    output_state = checkpoint["output_state"]
    state = deserialize_state(output_state)

    # 6. Determine next node via routing function
    step_name = checkpoint["step_name"]
    config = state["config"]
    routing_fn = make_routing_fn(step_name, config)
    routing_decision = routing_fn(state)

    next_node = _resolve_next_node(step_name, routing_decision)

    # 7. Return result
    return ResumeResult(
        state=state,
        next_node=next_node,
        resumed_from_step=step_name,
        orphaned_count=orphaned_count,
    )


def _resolve_next_node(source_node: str, routing_decision: str) -> str:
    """Resolve the routing decision to a concrete next node name.

    Maps the abstract routing decisions ("next", "retry", "escalate", "finalize",
    "end") to actual node names based on the pipeline graph topology.

    Args:
        source_node: The node that produced the routing decision.
        routing_decision: The string returned by the routing function.

    Returns:
        The name of the next node to execute.
    """
    # Path maps per source node (mirrors the design doc routing tables)
    path_maps: dict[str, dict[str, str]] = {
        "ingest": {"next": "extract_text", "escalate": "route_to_queue"},
        "extract_text": {
            "next": "chunk",
            "retry": "extract_text",
            "escalate": "route_to_queue",
        },
        "chunk": {"next": "embed", "escalate": "route_to_queue"},
        "embed": {
            "next": "extract_claims",
            "retry": "embed",
            "escalate": "route_to_queue",
        },
        "extract_claims": {
            "next": "match_rules",
            "retry": "extract_claims",
            "escalate": "route_to_queue",
        },
        "match_rules": {
            "next": "score_confidence",
            "retry": "match_rules",
            "escalate": "route_to_queue",
        },
        "score_confidence": {
            "next": "route_to_queue",
            "retry": "score_confidence",
            "escalate": "route_to_queue",
        },
        "route_to_queue": {
            "escalate": "human_review",
            "next": "finalize",
            "retry": "route_to_queue",
        },
        "human_review": {
            "finalize": "finalize",
            "escalate": "route_to_queue",
        },
        "finalize": {
            "end": "__end__",
            "retry": "finalize",
            "escalate": "__failed__",
        },
    }

    node_map = path_maps.get(source_node, {})
    return node_map.get(routing_decision, "route_to_queue")
