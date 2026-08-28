"""Human review interrupt node — suspends pipeline for human decisions on escalated claims.

This node is the second node of the Stay-Alive Stage. It inserts all escalated
claims into the approval_queue table with status "pending", then invokes
LangGraph's interrupt() to suspend graph execution. When the graph resumes
(triggered externally after all decisions arrive), it reads decisions and
populates them in state.

Dependency injection is used for the approval queue writer, decision reader,
and interrupt handler to enable unit testing without requiring LangGraph or
database infrastructure.
"""

from __future__ import annotations

from typing import Protocol

from src.pipeline.state import Decision, PipelineState


# --- Dependency Protocols ---


class ApprovalQueueWriter(Protocol):
    """Protocol for inserting escalated claims into the approval queue."""

    async def insert_pending(self, claim_ids: list[str], run_id: str) -> None:
        """Insert claim IDs into approval_queue with status 'pending'.

        Args:
            claim_ids: List of claim IDs to insert.
            run_id: The current pipeline run ID.
        """
        ...


class DecisionReader(Protocol):
    """Protocol for reading human decisions from the decisions table."""

    async def read_decisions(self, run_id: str) -> list[Decision]:
        """Read all decisions for the given run's escalated approval_queue entries.

        Args:
            run_id: The current pipeline run ID.

        Returns:
            List of Decision dicts with claim_id, approval_queue_id,
            decision_value, reviewer_id, and justification.
        """
        ...


class InterruptHandler(Protocol):
    """Protocol for the LangGraph interrupt mechanism."""

    def interrupt(self) -> None:
        """Suspend graph execution.

        In production, this calls LangGraph's interrupt().
        In tests, this is a no-op.
        """
        ...


# --- Node Implementation ---


async def human_review(
    state: PipelineState,
    *,
    queue_writer: ApprovalQueueWriter,
    decision_reader: DecisionReader,
    interrupt_handler: InterruptHandler,
) -> PipelineState:
    """Suspend pipeline for human review of escalated claims.

    1. Gets escalated claim IDs from state["queue_buckets"]["escalate"]
    2. Inserts them into approval_queue via ApprovalQueueWriter
    3. Calls interrupt_handler.interrupt() to suspend execution
    4. After resume: reads decisions via DecisionReader
    5. Populates state["decisions"] and returns completed

    Args:
        state: The current pipeline state with queue_buckets populated.
        queue_writer: Dependency for writing to the approval queue.
        decision_reader: Dependency for reading decisions after resume.
        interrupt_handler: Dependency for suspending graph execution.

    Returns:
        Updated PipelineState with decisions populated, node_status "completed",
        and completed_nodes updated.
    """
    try:
        escalated_claim_ids = state["queue_buckets"]["escalate"]
        run_id = state["run_id"]

        # Step 1: Insert escalated claims into approval_queue with status "pending"
        await queue_writer.insert_pending(escalated_claim_ids, run_id)

        # Step 2: Suspend graph execution (no-op in tests, interrupt() in production)
        interrupt_handler.interrupt()

        # --- Execution resumes here after external signal ---

        # Step 3: Read all decisions for this run's escalated items
        decisions = await decision_reader.read_decisions(run_id)

        # Step 4: Build successful result
        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append("human_review")

        return PipelineState(
            **{
                **state,
                "decisions": decisions,
                "current_node": "human_review",
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    except Exception as exc:
        # Any failure during human_review is transient (DB issues, etc.)
        return PipelineState(
            **{
                **state,
                "current_node": "human_review",
                "node_status": "error",
                "error_type": "transient",
                "error_detail": f"Human review node failure: {exc}",
                "completed_nodes": list(state.get("completed_nodes", [])),
            }
        )
