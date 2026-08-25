import asyncio
from typing import Dict, Optional
from uuid import UUID
from datetime import datetime, timezone

from backend.core.workflow.registry import workflow_registry
from backend.core.workflow.runner import WorkflowBlockedException, WorkflowEscalatedException
from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class TaskManager:
    """
    Manages background workflow execution.

    Responsibilities:
    - Queue workflow runs
    - Execute workflows asynchronously
    - Track running tasks
    - Cancel tasks
    - Report task status
    """

    def __init__(self, run_repo=None, stage_repo=None):
        # Don't hold repositories with sessions - create fresh sessions as needed
        self._running_tasks: Dict[str, asyncio.Task] = {}

    async def start_workflow(
        self,
        workflow_run_id: UUID,
        workflow_name: str,
        initial_state: dict,
        stages: list | None = None,
    ) -> None:
        """
        Start a workflow execution in the background.

        Args:
            workflow_run_id: ID of the workflow run
            workflow_name: Name of registered workflow
            initial_state: Initial workflow state
            stages: Optional list of StageNode instances. If provided, these are
                used instead of the registry stages (e.g. DB-wired 7-stage pipeline).
        """
        run_id_str = str(workflow_run_id)

        if run_id_str in self._running_tasks:
            logger.warning("workflow_already_running", run_id=run_id_str)
            return

        # Create fresh session and repositories for this workflow
        from backend.database import async_session_maker
        from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository

        # If custom stages provided (e.g., DB-wired 7-stage pipeline), use them.
        # Otherwise fall back to the registry stages.
        if stages is not None:
            workflow_def = workflow_registry.get(workflow_name)
            if not workflow_def:
                raise ValueError(f"Workflow '{workflow_name}' not found in registry")
            from backend.core.workflow.runner import WorkflowRunner

            # Create a task that manages its own session
            task = asyncio.create_task(
                self._execute_workflow_with_session(
                    workflow_run_id, workflow_name, initial_state, stages,
                    workflow_def["edges"], workflow_def["state_schema"]
                )
            )
        else:
            # Create a task that manages its own session
            task = asyncio.create_task(
                self._execute_workflow_with_session(
                    workflow_run_id, workflow_name, initial_state, None, None, None
                )
            )

        self._running_tasks[run_id_str] = task
        logger.info("workflow_task_started", run_id=run_id_str, workflow=workflow_name)

    async def _execute_workflow_with_session(
        self,
        workflow_run_id: UUID,
        workflow_name: str,
        initial_state: dict,
        stages: list | None,
        edges: list | None,
        state_schema: dict | None
    ) -> None:
        """Execute workflow with its own database session"""
        from backend.database import async_session_maker
        from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository
        from backend.core.workflow.runner import WorkflowRunner

        run_id_str = str(workflow_run_id)

        try:
            # Create fresh session for this workflow execution
            async with async_session_maker() as session:
                run_repo = WorkflowRunRepository(session)
                stage_repo = WorkflowStageRepository(session)

                # For tariff workflow, build stages with this session
                if workflow_name == "tariff_classification":
                    from backend.modules.tariff.workflow import build_tariff_stages
                    workflow_def = workflow_registry.get(workflow_name)
                    if not workflow_def:
                        raise ValueError(f"Workflow '{workflow_name}' not found in registry")

                    # Build real stages with database session
                    db_stages = build_tariff_stages(db_session=session)

                    runner = WorkflowRunner(
                        workflow_name=workflow_name,
                        stages=db_stages,
                        edges=workflow_def["edges"],
                        state_schema=workflow_def["state_schema"],
                        stage_repository=stage_repo,
                    )
                elif workflow_name == "screenplay":
                    from backend.modules.screenplay.workflow import build_screenplay_stages
                    workflow_def = workflow_registry.get(workflow_name)
                    if not workflow_def:
                        raise ValueError(f"Workflow '{workflow_name}' not found in registry")

                    db_stages = build_screenplay_stages(db_session=session)

                    runner = WorkflowRunner(
                        workflow_name=workflow_name,
                        stages=db_stages,
                        edges=workflow_def["edges"],
                        state_schema=workflow_def["state_schema"],
                        stage_repository=stage_repo,
                    )
                elif stages is not None:
                    # Custom stages path (other workflows)
                    runner = WorkflowRunner(
                        workflow_name=workflow_name,
                        stages=stages,
                        edges=edges,
                        state_schema=state_schema,
                        stage_repository=stage_repo,
                    )
                else:
                    # Registry stages path (non-tariff workflows)
                    runner = workflow_registry.create_runner(workflow_name, stage_repo)

                await runner.run(initial_state, run_repo)
                logger.info("workflow_task_completed", run_id=run_id_str)
        except asyncio.CancelledError:
            logger.info("workflow_task_cancelled", run_id=run_id_str)
        except WorkflowEscalatedException as e:
            logger.info("workflow_task_paused_for_review", run_id=run_id_str, reason=e.reason)
        except WorkflowBlockedException as e:
            logger.warning("workflow_task_blocked", run_id=run_id_str, reason=e.reason)
        except Exception as e:
            logger.error("workflow_task_failed", run_id=run_id_str, error=str(e), exc_info=True)
            try:
                async with async_session_maker() as err_session:
                    err_run_repo = WorkflowRunRepository(err_session)
                    err_stage_repo = WorkflowStageRepository(err_session)
                    await err_run_repo.update(
                        workflow_run_id,
                        status="failed",
                        completed_at=datetime.now(timezone.utc),
                        current_stage=None,
                    )
                    existing_stages = await err_stage_repo.list_by_run(workflow_run_id)
                    if not existing_stages:
                        await err_stage_repo.create(
                            run_id=workflow_run_id,
                            stage_name="initialization",
                            status="failed",
                            started_at=datetime.now(timezone.utc),
                            completed_at=datetime.now(timezone.utc),
                            error_message=str(e),
                        )
            except Exception as update_err:
                logger.error("failed_to_update_run_status", run_id=run_id_str, error=str(update_err))
        finally:
            # Clean up task from running tasks
            if run_id_str in self._running_tasks:
                del self._running_tasks[run_id_str]


    async def resume_workflow(self, workflow_run_id: UUID, workflow_name: str) -> None:
        """
        Resume a paused (waiting) workflow from its last completed checkpoint.

        Builds fresh stages with a new DB session and calls runner.resume().
        """
        run_id_str = str(workflow_run_id)

        if run_id_str in self._running_tasks:
            logger.warning("workflow_already_running_on_resume", run_id=run_id_str)
            return

        task = asyncio.create_task(
            self._resume_workflow_with_session(workflow_run_id, workflow_name)
        )
        self._running_tasks[run_id_str] = task
        logger.info("workflow_resume_task_started", run_id=run_id_str)

    async def _resume_workflow_with_session(
        self,
        workflow_run_id: UUID,
        workflow_name: str,
    ) -> None:
        """Resume workflow with its own database session."""
        from backend.database import async_session_maker
        from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository
        from backend.core.workflow.runner import WorkflowRunner

        run_id_str = str(workflow_run_id)

        try:
            async with async_session_maker() as session:
                run_repo = WorkflowRunRepository(session)
                stage_repo = WorkflowStageRepository(session)

                if workflow_name == "tariff_classification":
                    from backend.modules.tariff.workflow import build_tariff_stages
                    workflow_def = workflow_registry.get(workflow_name)
                    if not workflow_def:
                        raise ValueError(f"Workflow '{workflow_name}' not found in registry")
                    db_stages = build_tariff_stages(db_session=session)
                    runner = WorkflowRunner(
                        workflow_name=workflow_name,
                        stages=db_stages,
                        edges=workflow_def["edges"],
                        state_schema=workflow_def["state_schema"],
                        stage_repository=stage_repo,
                    )
                elif workflow_name == "screenplay":
                    from backend.modules.screenplay.workflow import build_screenplay_stages
                    workflow_def = workflow_registry.get(workflow_name)
                    if not workflow_def:
                        raise ValueError(f"Workflow '{workflow_name}' not found in registry")
                    db_stages = build_screenplay_stages(db_session=session)
                    runner = WorkflowRunner(
                        workflow_name=workflow_name,
                        stages=db_stages,
                        edges=workflow_def["edges"],
                        state_schema=workflow_def["state_schema"],
                        stage_repository=stage_repo,
                    )
                else:
                    runner = workflow_registry.create_runner(workflow_name, stage_repo)

                await runner.resume(workflow_run_id, run_repo)
                logger.info("workflow_resume_completed", run_id=run_id_str)
        except asyncio.CancelledError:
            logger.info("workflow_resume_cancelled", run_id=run_id_str)
        except WorkflowEscalatedException as e:
            logger.info("workflow_resume_paused_for_review", run_id=run_id_str, reason=e.reason)
        except WorkflowBlockedException as e:
            logger.warning("workflow_resume_blocked", run_id=run_id_str, reason=e.reason)
        except Exception as e:
            logger.error("workflow_resume_failed", run_id=run_id_str, error=str(e), exc_info=True)
            try:
                async with async_session_maker() as err_session:
                    err_run_repo = WorkflowRunRepository(err_session)
                    await err_run_repo.update(
                        workflow_run_id,
                        status="failed",
                        completed_at=datetime.now(timezone.utc),
                    )
            except Exception as update_err:
                logger.error("failed_to_update_run_status", run_id=run_id_str, error=str(update_err))
        finally:
            if run_id_str in self._running_tasks:
                del self._running_tasks[run_id_str]

    async def cancel_workflow(self, workflow_run_id: UUID) -> bool:
        """
        Cancel a running workflow.

        Args:
            workflow_run_id: ID of the workflow run to cancel

        Returns:
            True if cancelled, False if not running
        """
        run_id_str = str(workflow_run_id)

        was_running = False
        if run_id_str in self._running_tasks:
            task = self._running_tasks[run_id_str]
            task.cancel()
            was_running = True

        # Update run status with fresh session
        from backend.database import async_session_maker
        from backend.repositories.workflow import WorkflowRunRepository
        from datetime import datetime, timezone

        try:
            async with async_session_maker() as session:
                run_repo = WorkflowRunRepository(session)
                await run_repo.update(
                    workflow_run_id,
                    status="cancelled",
                    completed_at=datetime.now(timezone.utc),
                    current_stage=None
                )
                await session.commit()
        except Exception as e:
            logger.error("error_updating_cancelled_status", run_id=run_id_str, error=str(e))

        logger.info("workflow_cancelled", run_id=run_id_str, was_running=was_running)
        return True

    def is_running(self, workflow_run_id: UUID) -> bool:
        """Check if a workflow is currently running"""
        return str(workflow_run_id) in self._running_tasks

    def get_running_count(self) -> int:
        """Get count of currently running workflows"""
        return len(self._running_tasks)

    def get_running_ids(self) -> list[str]:
        """Get list of running workflow run IDs"""
        return list(self._running_tasks.keys())


# Global task manager instance (instantiated with dependencies)
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """Get global task manager instance"""
    if _task_manager is None:
        raise RuntimeError("TaskManager not initialized. Call init_task_manager() first.")
    return _task_manager


def init_task_manager() -> None:
    """Initialize global task manager"""
    global _task_manager
    _task_manager = TaskManager()
