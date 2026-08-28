"""Finalize node — writes final statuses, closes the run, and emits audit events.

This is the terminal node of the Stay-Alive Stage. It collects approved and
rejected claim IDs from queue_buckets and human review decisions, then writes
them to the database in a single transaction.

Finalization logic:
1. Determine approved claims: auto_approve bucket + decisions with value "approved"
2. Determine rejected claims: auto_reject bucket + decisions with value "rejected"
3. Handle human-review-skipped case: if decisions is empty, use only auto_approve/auto_reject
4. Call writer.finalize_run() within a single transaction
5. On success: return completed state
6. On failure (exception): return transient error state
"""

from __future__ import annotations

from typing import Optional, Protocol

from src.pipeline.state import PipelineState


class FinalizeWriter(Protocol):
    """Protocol for database operations during finalization.

    Implementations must perform all writes within a single DB transaction:
    - Write verified (approved) claims
    - Write rejected claims
    - Update runs to "completed"
    - Insert audit events
    """

    async def finalize_run(
        self,
        run_id: str,
        auto_approve_ids: list[str],
        auto_reject_ids: list[str],
        approved_ids: list[str],
        rejected_ids: list[str],
    ) -> None:
        """Finalize a pipeline run within a single DB transaction.

        Args:
            run_id: The pipeline run identifier.
            auto_approve_ids: Claim IDs auto-approved by the routing node.
            auto_reject_ids: Claim IDs auto-rejected by the routing node.
            approved_ids: Claim IDs approved by human reviewers.
            rejected_ids: Claim IDs rejected by human reviewers.

        Raises:
            Exception: On any DB transaction failure.
        """
        ...


# Module-level writer instance, injectable for testing
_writer: Optional[FinalizeWriter] = None


def set_writer(writer: FinalizeWriter) -> None:
    """Inject a FinalizeWriter implementation.

    Args:
        writer: The writer instance to use for finalization.
    """
    global _writer
    _writer = writer


def get_writer() -> Optional[FinalizeWriter]:
    """Get the currently configured FinalizeWriter.

    Returns:
        The configured writer or None if not set.
    """
    return _writer


async def finalize(state: PipelineState) -> PipelineState:
    """Finalize the pipeline run by persisting results and closing the run.

    Collects approved/rejected claim IDs from queue_buckets and decisions,
    then writes them via the FinalizeWriter in a single DB transaction.

    Args:
        state: The current pipeline state containing queue_buckets, decisions,
               run_id, and config.

    Returns:
        Updated PipelineState with current_node set to "finalize",
        node_status "completed" on success or "error" with error_type
        "transient" on DB failure.
    """
    try:
        writer = _writer
        if writer is None:
            return _transient_error_state(
                state, error_detail="FinalizeWriter not configured"
            )

        run_id = state["run_id"]
        queue_buckets = state["queue_buckets"]
        decisions = list(state.get("decisions", []))

        # Auto-approve and auto-reject from routing
        auto_approve_ids = list(queue_buckets["auto_approve"])
        auto_reject_ids = list(queue_buckets["auto_reject"])

        # Human review decisions (may be empty if review was skipped)
        approved_ids: list[str] = []
        rejected_ids: list[str] = []

        for decision in decisions:
            if decision["decision_value"] == "approved":
                approved_ids.append(decision["claim_id"])
            elif decision["decision_value"] == "rejected":
                rejected_ids.append(decision["claim_id"])

        # Execute the finalization within a single DB transaction
        await writer.finalize_run(
            run_id=run_id,
            auto_approve_ids=auto_approve_ids,
            auto_reject_ids=auto_reject_ids,
            approved_ids=approved_ids,
            rejected_ids=rejected_ids,
        )

        # Success
        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append("finalize")

        return PipelineState(
            **{
                **state,
                "current_node": "finalize",
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    except Exception as exc:
        return _transient_error_state(
            state,
            error_detail=f"DB transaction failure during finalization: {exc}",
        )


def _transient_error_state(
    state: PipelineState, *, error_detail: str
) -> PipelineState:
    """Return a transient error state for finalize."""
    return PipelineState(
        **{
            **state,
            "current_node": "finalize",
            "node_status": "error",
            "error_type": "transient",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )
