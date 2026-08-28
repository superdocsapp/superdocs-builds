"""Checkpoint persistence layer for per-node durable state snapshots.

Provides functions to create run_steps rows and write checkpoints
(serialized state) to PostgreSQL within a single transaction. Uses
dependency injection via the CheckpointStore protocol to enable unit
testing without a real database.

Requirements: 6.1, 6.2, 6.4, 6.5, 6.7
"""

from datetime import datetime, timezone
from typing import Any, Protocol

from src.pipeline.serialization import serialize_state
from src.pipeline.state import PipelineState


class CheckpointStore(Protocol):
    """Abstract protocol for checkpoint persistence operations.

    Implementations back onto SQLAlchemy sessions (production) or
    in-memory stores (testing). All methods are synchronous to match
    SQLAlchemy's default session API; async wrappers can be added at
    the caller level.
    """

    def create_step(
        self,
        run_id: str,
        step_name: str,
        step_order: int,
    ) -> None:
        """Insert a run_steps row with status 'running' and started_at set.

        Args:
            run_id: UUID string of the owning run.
            step_name: Name of the pipeline node being executed.
            step_order: Monotonically increasing sequence number.

        Raises:
            Exception: On database/store failure.
        """
        ...

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
        """Update the run_steps row with serialized state, status, and ended_at.

        This must execute within a single transaction: serialize state,
        write to output_state, update status, and set ended_at atomically.

        Args:
            run_id: UUID string of the owning run.
            step_name: Name of the pipeline node.
            step_order: Sequence number identifying the step row.
            output_state: Already-serialized state dictionary (JSONB-ready).
            status: Final status for the step ('completed' or 'skipped').
            ended_at: Timestamp when the step finished.
            **kwargs: Optional cost tracking fields (duration_ms, input_tokens,
                output_tokens, cost_usd).

        Raises:
            Exception: On database/store failure.
        """
        ...


class CheckpointWriteError(Exception):
    """Raised when a checkpoint write fails.

    This is always treated as a transient error, triggering retry logic.
    """

    pass


def create_step_row(
    store: CheckpointStore,
    run_id: str,
    step_name: str,
    step_order: int,
) -> None:
    """Create a run_steps row with status 'running' and started_at = now().

    This is called before a node begins execution, so the row exists
    to receive the checkpoint upon successful completion.

    Args:
        store: The checkpoint store implementation.
        run_id: UUID string of the owning run.
        step_name: Name of the pipeline node about to execute.
        step_order: Monotonically increasing step sequence number.

    Raises:
        CheckpointWriteError: If the store operation fails (transient).
    """
    try:
        store.create_step(run_id, step_name, step_order)
    except Exception as exc:
        raise CheckpointWriteError(
            f"Failed to create step row for {step_name} "
            f"(run_id={run_id}, step_order={step_order}): {exc}"
        ) from exc


def write_checkpoint(
    store: CheckpointStore,
    run_id: str,
    step_name: str,
    step_order: int,
    state: PipelineState,
) -> None:
    """Persist a checkpoint after a node completes successfully.

    Performs a single-transaction write:
    1. Serialize state via serialize_state()
    2. Write serialized state to run_steps.output_state
    3. Update status to 'completed' or 'skipped' based on state['node_status']
    4. Set ended_at timestamp

    Only called when node_status is 'completed' or 'skipped'. Never called
    for error states (Requirement 6.4).

    Args:
        store: The checkpoint store implementation.
        run_id: UUID string of the owning run.
        step_name: Name of the pipeline node that completed.
        step_order: Sequence number identifying the step row.
        state: The PipelineState to checkpoint.

    Raises:
        CheckpointWriteError: If the store operation fails (transient error,
            triggering retry logic per Requirement 6.7).
    """
    try:
        serialized = serialize_state(state)
        status = state["node_status"]  # "completed" or "skipped"
        ended_at = datetime.now(timezone.utc)

        store.write_checkpoint(
            run_id=run_id,
            step_name=step_name,
            step_order=step_order,
            output_state=serialized,
            status=status,
            ended_at=ended_at,
        )
    except CheckpointWriteError:
        # Re-raise if already wrapped
        raise
    except Exception as exc:
        raise CheckpointWriteError(
            f"Failed to write checkpoint for {step_name} "
            f"(run_id={run_id}, step_order={step_order}): {exc}"
        ) from exc
