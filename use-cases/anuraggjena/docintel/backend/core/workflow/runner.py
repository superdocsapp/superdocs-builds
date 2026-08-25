from typing import Dict, List, Any, Type, Optional
from uuid import UUID
from langgraph.graph import StateGraph, END
from pydantic import BaseModel
import json
import asyncio
from datetime import datetime, timezone

from backend.core.workflow.stage import StageNode, WorkflowState, TState
from backend.core.workflow.decisions import (
    DecisionEngine,
    DecisionContext,
    DecisionResult,
    WorkflowDecision
)
from backend.logging_config import get_logger
from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository
from backend.models.workflow import WorkflowRun

logger = get_logger(__name__)


class WorkflowEscalatedException(Exception):
    """Raised when workflow needs human intervention."""
    def __init__(self, reason: str, metadata: Dict[str, Any]):
        self.reason = reason
        self.metadata = metadata
        super().__init__(reason)


class WorkflowBlockedException(Exception):
    """Raised when workflow is permanently blocked."""
    def __init__(self, reason: str, metadata: Dict[str, Any]):
        self.reason = reason
        self.metadata = metadata
        super().__init__(reason)


class WorkflowRunner:
    """
    Orchestrates workflow execution using LangGraph.

    Responsibilities:
    - Build LangGraph from stage definitions
    - Execute workflow with state management
    - Track progress in database
    - Handle errors and resume
    """

    def __init__(
        self,
        workflow_name: str,
        stages: List[StageNode],
        edges: List[tuple[str, str]],
        state_schema: Type[TState],
        stage_repository: WorkflowStageRepository,
        decision_engine: Optional[DecisionEngine] = None
    ):
        """
        Initialize workflow runner.

        Args:
            workflow_name: Name of the workflow
            stages: List of stage nodes
            edges: List of (from_stage, to_stage) tuples
            state_schema: Pydantic model for workflow state
            stage_repository: Repository for workflow stage persistence
            decision_engine: Optional decision engine for agentic behavior
        """
        self.workflow_name = workflow_name
        self.stages = {stage.name: stage for stage in stages}
        self.edges = edges
        self.state_schema = state_schema
        self.stage_repository = stage_repository
        self.decision_engine = decision_engine or DecisionEngine()
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build LangGraph from stage definitions"""
        logger.info("building_workflow_graph", workflow=self.workflow_name)

        # Create graph with state schema
        graph = StateGraph(self.state_schema)

        # Add nodes with persistence wrapper
        for stage_name, stage in self.stages.items():
            wrapped_stage = self._wrap_stage_with_persistence(stage)
            graph.add_node(stage_name, wrapped_stage)

        # Add edges
        for from_stage, to_stage in self.edges:
            if to_stage == "END":
                graph.add_edge(from_stage, END)
            else:
                graph.add_edge(from_stage, to_stage)

        # Set entry point (first stage)
        if self.edges:
            first_stage = self.edges[0][0]
            graph.set_entry_point(first_stage)

        return graph.compile()

    def _wrap_stage_with_persistence(self, stage: StageNode) -> callable:
        """Wrap stage execution with persistence and decision logic"""
        async def wrapped(state) -> dict:
            # Handle both dict and Pydantic model state
            if hasattr(state, "workflow_run_id") and state.workflow_run_id:
                workflow_run_id = UUID(str(state.workflow_run_id))
                state_dict = state.model_dump() if hasattr(state, 'model_dump') else dict(state)
            else:
                raw_run_id = state.get("workflow_run_id") if isinstance(state, dict) else getattr(state, "workflow_run_id", None)
                workflow_run_id = UUID(str(raw_run_id)) if raw_run_id else None
                state_dict = state

            # Find or create stage record
            stage_record = None
            if workflow_run_id:
                stage_record = await self.stage_repository.get_by_run_and_name(
                    workflow_run_id, stage.name
                )

            # IDEMPOTENCY: if this stage already completed (e.g. on a previous run
            # before a HITL pause), skip re-execution and return the saved checkpoint.
            # This prevents superdocs_instruction (and other completed stages) from
            # re-running when the workflow is resumed after human review.
            if stage_record and stage_record.status in ("completed", "skipped"):
                logger.info(
                    "stage_already_completed_skip",
                    stage=stage.name,
                    status=stage_record.status,
                    run_id=str(workflow_run_id),
                )
                if stage_record.checkpoint_data:
                    try:
                        saved = json.loads(stage_record.checkpoint_data)
                        # Return only the keys that differ from the incoming state
                        # so LangGraph merges them correctly.
                        incoming = state_dict if isinstance(state_dict, dict) else {}
                        return {k: v for k, v in saved.items() if k not in incoming or incoming[k] != v}
                    except (json.JSONDecodeError, TypeError):
                        pass
                return {}

            if hasattr(self, "_current_run_repo") and self._current_run_repo and workflow_run_id:
                try:
                    await self._current_run_repo.update(workflow_run_id, current_stage=stage.name)
                except Exception as update_exc:
                    logger.warning("failed_to_update_current_stage", stage=stage.name, error=str(update_exc))

            retry_count = 0
            if not stage_record:
                # Create new stage record
                stage_record = await self.stage_repository.create(
                    run_id=workflow_run_id,
                    stage_name=stage.name,
                    status="running",
                    started_at=datetime.now(timezone.utc).replace(tzinfo=None)
                )
            else:
                # Get current retry count
                retry_count = (stage_record.retry_count or 0)

            # Capture stage_record.id before retry loop to avoid lazy-load issues
            # after session expiration/rollback
            stage_record_id = stage_record.id

            # Retry loop
            last_error = None
            for attempt in range(retry_count, self.decision_engine.max_retries + 1):
                # Update retry count and clear any stale error from previous attempts
                await self.stage_repository.update(
                    stage_record_id,
                    status="running",
                    started_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    retry_count=attempt,
                    error_message=None,
                )

                start_time = datetime.now(timezone.utc).replace(tzinfo=None)
                error_occurred = None
                updates = {}

                try:
                    # Execute stage
                    updates = await stage(state)

                    # Calculate execution time
                    end_time = datetime.now(timezone.utc).replace(tzinfo=None)
                    execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

                    # Save checkpoint — use pydantic-aware serialisation
                    def _default(obj):
                        if hasattr(obj, "model_dump"):
                            return obj.model_dump()
                        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

                    checkpoint_data = json.dumps({**state_dict, **updates}, default=_default)

                    # Make decision based on stage result
                    decision_context = DecisionContext(
                        stage_name=stage.name,
                        stage_result=updates,
                        workflow_state=state_dict,
                        retry_count=attempt,
                        error=None
                    )
                    decision = await self.decision_engine.decide(decision_context)

                    # Persist decision (ensuring stale errors are cleared)
                    await self.stage_repository.update(
                        stage_record_id,
                        decision_type=decision.decision.value,
                        decision_reason=decision.reason,
                        decision_metadata=json.dumps(decision.metadata),
                        error_message=None,
                    )

                    # Handle decision
                    return await self._execute_decision(
                        decision,
                        stage,
                        stage_record_id,
                        state,
                        updates,
                        checkpoint_data,
                        execution_time_ms,
                        end_time
                    )

                except WorkflowEscalatedException as e:
                    # Update stage status to waiting before re-raising escalation
                    end_time = datetime.now(timezone.utc).replace(tzinfo=None)
                    execution_time_ms = int((end_time - start_time).total_seconds() * 1000)
                    try:
                        await self.stage_repository.update(
                            stage_record_id,
                            status="waiting",
                            completed_at=None,
                            execution_time_ms=execution_time_ms,
                            decision_type="escalate",
                            decision_reason=f"Waiting for human review: {e.reason}",
                            decision_metadata=json.dumps(e.metadata or {}),
                            error_message=None
                        )
                    except Exception as stage_upd_err:
                        logger.warning("failed_to_update_stage_on_escalation", error=str(stage_upd_err))
                    # Re-raise escalation without retry
                    raise

                except WorkflowBlockedException:
                    # Re-raise block without retry
                    raise

                except Exception as e:
                    last_error = e
                    end_time = datetime.now(timezone.utc).replace(tzinfo=None)
                    execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

                    # Make decision on error
                    decision_context = DecisionContext(
                        stage_name=stage.name,
                        stage_result=updates,
                        workflow_state=state_dict,
                        retry_count=attempt,
                        error=e
                    )
                    decision = await self.decision_engine.decide(decision_context)

                    # Persist decision (use captured ID to avoid lazy-load after rollback)
                    await self.stage_repository.update(
                        stage_record_id,
                        decision_type=decision.decision.value,
                        decision_reason=decision.reason,
                        decision_metadata=json.dumps(decision.metadata),
                        error_message=str(e)
                    )

                    # Check decision
                    if decision.decision == WorkflowDecision.RETRY:
                        # Backoff and continue loop
                        backoff_seconds = decision.metadata.get("backoff_seconds", 2)
                        logger.info(
                            "stage_retry_scheduled",
                            stage=stage.name,
                            backoff_seconds=backoff_seconds,
                            retry_count=attempt
                        )
                        await asyncio.sleep(backoff_seconds)
                        continue  # Retry

                    elif decision.decision == WorkflowDecision.BLOCK:
                        # Permanent failure
                        await self.stage_repository.update(
                            stage_record_id,
                            status="failed",
                            completed_at=end_time,
                            execution_time_ms=execution_time_ms
                        )
                        raise WorkflowBlockedException(
                            f"Stage {stage.name} failed: {decision.reason}",
                            decision.metadata
                        )

                    else:
                        # Unknown error decision - fail
                        await self.stage_repository.update(
                            stage_record_id,
                            status="failed",
                            completed_at=end_time,
                            execution_time_ms=execution_time_ms
                        )
                        raise e

            # If we get here, all retries exhausted
            if last_error:
                raise WorkflowBlockedException(
                    f"Stage {stage.name} failed after {self.decision_engine.max_retries} retries",
                    {"last_error": str(last_error)}
                )

            return {}

        return wrapped

    async def _execute_decision(
        self,
        decision: DecisionResult,
        stage: StageNode,
        stage_record_id,
        state,
        updates: Dict[str, Any],
        checkpoint_data: str,
        execution_time_ms: int,
        end_time: datetime
    ) -> Dict[str, Any]:
        """Execute the decision made by DecisionEngine."""

        if decision.decision == WorkflowDecision.CONTINUE:
            # Normal progression
            await self.stage_repository.update(
                stage_record_id,
                status="completed",
                completed_at=end_time,
                execution_time_ms=execution_time_ms,
                checkpoint_data=checkpoint_data,
                error_message=None,
            )
            return updates

        elif decision.decision == WorkflowDecision.SKIP:
            # Skip stage - mark as skipped
            logger.info(
                "stage_skipped",
                stage=stage.name,
                reason=decision.reason
            )
            await self.stage_repository.update(
                stage_record_id,
                status="skipped",
                completed_at=end_time,
                execution_time_ms=execution_time_ms,
                checkpoint_data=checkpoint_data,
                error_message=None,
            )
            # Return empty updates to skip
            return {}

        elif decision.decision == WorkflowDecision.ESCALATE:
            # Escalate to human - pause workflow
            logger.warning(
                "stage_escalated",
                stage=stage.name,
                reason=decision.reason
            )
            await self.stage_repository.update(
                stage_record_id,
                status="escalated",
                completed_at=end_time,
                execution_time_ms=execution_time_ms,
                checkpoint_data=checkpoint_data,
                error_message=None,
            )
            # Raise exception to halt workflow
            raise WorkflowEscalatedException(decision.reason, decision.metadata)

        elif decision.decision == WorkflowDecision.TARGETED_UPDATE:
            # Route to focused update path
            logger.info(
                "targeted_update_triggered",
                stage=stage.name,
                reason=decision.reason
            )
            await self.stage_repository.update(
                stage_record_id,
                status="completed",
                completed_at=end_time,
                execution_time_ms=execution_time_ms,
                checkpoint_data=checkpoint_data,
                error_message=None,
            )
            # Add focused update flag to state
            updates["_focused_update_active"] = True
            return updates

        elif decision.decision == WorkflowDecision.BLOCK:
            # Permanent failure - block workflow
            logger.error(
                "stage_blocked",
                stage=stage.name,
                reason=decision.reason
            )
            await self.stage_repository.update(
                stage_record_id,
                status="blocked",
                completed_at=end_time,
                execution_time_ms=execution_time_ms
            )
            raise WorkflowBlockedException(decision.reason, decision.metadata)

        else:
            # Unknown decision - default to continue
            logger.warning(
                "unknown_decision",
                decision=decision.decision,
                stage=stage.name
            )
            await self.stage_repository.update(
                stage_record_id,
                status="completed",
                completed_at=end_time,
                execution_time_ms=execution_time_ms,
                checkpoint_data=checkpoint_data,
                error_message=None,
            )
            return updates

    async def run(
        self,
        initial_state: Dict[str, Any],
        run_repository: WorkflowRunRepository
    ) -> Dict[str, Any]:
        """
        Execute workflow from initial state.

        Args:
            initial_state: Initial state dictionary
            run_repository: Repository for workflow run persistence

        Returns:
            Final state after workflow completion
        """
        logger.info("workflow_started", workflow=self.workflow_name)
        self._current_run_repo = run_repository

        # Create workflow run record
        workflow_run_id = initial_state.get("workflow_run_id")

        try:
            # Update current stage before execution starts
            if workflow_run_id:
                run_obj = await run_repository.get_by_id(UUID(workflow_run_id)) if hasattr(run_repository, "get_by_id") else None
                update_kwargs: Dict[str, Any] = {
                    "status": "running",
                    "completed_at": None,
                    "current_stage": self.edges[0][0] if self.edges else None,
                }
                if run_obj and getattr(run_obj, "started_at", None) is None:
                    update_kwargs["started_at"] = datetime.now(timezone.utc)
                await run_repository.update(
                    UUID(workflow_run_id),
                    **update_kwargs
                )

            # Execute graph
            final_state = await self.graph.ainvoke(initial_state)

            # Update run status
            if workflow_run_id:
                run_obj = await run_repository.get_by_id(UUID(workflow_run_id)) if hasattr(run_repository, "get_by_id") else None
                if run_obj and getattr(run_obj, "status", None) == "cancelled":
                    logger.info("workflow_was_cancelled_ignoring_completion", run_id=workflow_run_id)
                    return final_state

                await run_repository.update(
                    UUID(workflow_run_id),
                    status="completed",
                    completed_at=datetime.now(timezone.utc),
                    current_stage=None
                )

            logger.info("workflow_completed", workflow=self.workflow_name)
            return final_state

        except asyncio.CancelledError:
            logger.info(
                "workflow_cancelled",
                workflow=self.workflow_name,
                run_id=workflow_run_id
            )
            if workflow_run_id:
                await run_repository.update(
                    UUID(workflow_run_id),
                    status="cancelled",
                    completed_at=datetime.now(timezone.utc),
                    current_stage=None
                )
            raise

        except WorkflowEscalatedException as e:
            logger.warning(
                "workflow_escalated",
                workflow=self.workflow_name,
                reason=e.reason
            )

            # Update run status to waiting
            if workflow_run_id:
                run_obj = await run_repository.get_by_id(UUID(workflow_run_id)) if hasattr(run_repository, "get_by_id") else None
                if run_obj and getattr(run_obj, "status", None) == "cancelled":
                    logger.info("workflow_was_cancelled_ignoring_escalation", run_id=workflow_run_id)
                    return {"status": "cancelled", "reason": e.reason}

                await run_repository.update(
                    UUID(workflow_run_id),
                    status="waiting",
                    current_stage="human_review_required"
                )

            # Don't raise - this is a controlled pause
            # Return current state for potential resume
            return {"status": "escalated", "reason": e.reason, "metadata": e.metadata}

        except WorkflowBlockedException as e:
            logger.error(
                "workflow_blocked",
                workflow=self.workflow_name,
                reason=e.reason
            )

            # Update run status to blocked
            if workflow_run_id:
                run_obj = await run_repository.get_by_id(UUID(workflow_run_id)) if hasattr(run_repository, "get_by_id") else None
                if run_obj and getattr(run_obj, "status", None) == "cancelled":
                    logger.info("workflow_was_cancelled_ignoring_blocked", run_id=workflow_run_id)
                    raise

                await run_repository.update(
                    UUID(workflow_run_id),
                    status="blocked",
                    completed_at=datetime.now(timezone.utc),
                    current_stage=None
                )

            raise

        except Exception as e:
            logger.error("workflow_failed", workflow=self.workflow_name, error=str(e))

            # Update run status
            if workflow_run_id:
                run_obj = await run_repository.get_by_id(UUID(workflow_run_id)) if hasattr(run_repository, "get_by_id") else None
                if run_obj and getattr(run_obj, "status", None) == "cancelled":
                    logger.info("workflow_was_cancelled_ignoring_failure", run_id=workflow_run_id)
                    raise

                await run_repository.update(
                    UUID(workflow_run_id),
                    status="failed",
                    completed_at=datetime.now(timezone.utc),
                    current_stage=None
                )

            raise

    async def resume(
        self,
        workflow_run_id: UUID,
        run_repository: WorkflowRunRepository
    ) -> Dict[str, Any]:
        """
        Resume workflow from last checkpoint.

        Args:
            workflow_run_id: ID of the workflow run to resume
            run_repository: Repository for workflow run persistence

        Returns:
            Final state after workflow completion
        """
        logger.info("workflow_resumed", workflow=self.workflow_name, run_id=str(workflow_run_id))

        # Get all stages for this run
        stages = await self.stage_repository.list_by_run(workflow_run_id)

        # Find last completed stage with valid checkpoint
        completed_stages = [
            s for s in stages
            if s and s.status in ("completed", "skipped") and s.checkpoint_data
        ]

        if not completed_stages:
            raise ValueError("No completed stages found to resume from")

        # Get checkpoint from last completed stage
        last_stage = completed_stages[-1]
        try:
            state = json.loads(last_stage.checkpoint_data)
        except Exception as e:
            raise ValueError(f"Invalid checkpoint data: {e}")

        # Continue execution. Completed stages are idempotency-skipped inside
        # _wrap_stage_with_persistence, so the graph runs from the top but only
        # executes stages that haven't completed yet.
        logger.info(
            "workflow_resuming_from_checkpoint",
            workflow=self.workflow_name,
            last_completed_stage=last_stage.stage_name,
            run_id=str(workflow_run_id),
        )
        return await self.run(state, run_repository)
