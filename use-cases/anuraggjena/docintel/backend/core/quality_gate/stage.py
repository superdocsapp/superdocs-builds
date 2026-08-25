from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.core.quality_gate.engine import QualityGateEngine
from backend.core.quality_gate.config import QualityGateSettings
from backend.core.quality_gate.checks import BaseCheck
from backend.repositories.quality_gate import QualityGateConfigRepository, QualityGateResultRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class QualityGateStage(StageNode):
    """Workflow stage that runs quality gate checks."""

    def __init__(
        self,
        checks: List[BaseCheck],
        config_repository: Optional[QualityGateConfigRepository] = None,
        result_repository: Optional[QualityGateResultRepository] = None,
    ):
        super().__init__(name="quality_gate")
        self.engine = QualityGateEngine()
        self.engine.register_many(checks)
        self.config_repository = config_repository
        self.result_repository = result_repository

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        # Support both dict and Pydantic model state
        workspace_id = state.get("workspace_id") if isinstance(state, dict) else getattr(state, "workspace_id", None)
        workflow_run_id = state.get("workflow_run_id") if isinstance(state, dict) else getattr(state, "workflow_run_id", None)

        # Load config from DB if repository available
        settings = QualityGateSettings.default()
        config_record = None
        if self.config_repository and workspace_id:
            try:
                try:
                    ws_uuid = UUID(str(workspace_id))
                except (ValueError, TypeError):
                    ws_uuid = workspace_id
                config_record = await self.config_repository.get_by_workspace(ws_uuid)
                settings = QualityGateSettings.from_db_config(config_record)
            except Exception as e:
                logger.warning("quality_gate_config_load_failed", error=str(e))

        if not settings.enabled:
            logger.info("quality_gate_skipped", reason="disabled")
            return {"quality_gate_status": "skipped", "quality_gate_details": []}

        gate_result = await self.engine.run(
            state=state,
            config=settings.checks_config,
            enabled_checks=settings.enabled_checks,
        )

        # Persist result if repository available
        if self.result_repository and workflow_run_id:
            try:
                try:
                    run_uuid = UUID(str(workflow_run_id))
                except (ValueError, TypeError):
                    run_uuid = workflow_run_id
                cfg_id = None
                if config_record and getattr(config_record, "id", None):
                    try:
                        cfg_id = UUID(str(config_record.id))
                    except (ValueError, TypeError):
                        cfg_id = config_record.id

                await self.result_repository.create(
                    workflow_run_id=run_uuid,
                    config_id=cfg_id,
                    status=gate_result.status,
                    checks_run=gate_result.checks_run,
                    checks_passed=gate_result.checks_passed,
                    checks_failed=gate_result.checks_failed,
                    blocking=gate_result.blocking,
                    details=gate_result.to_details(),
                )
            except Exception as e:
                logger.error("quality_gate_result_save_failed", error=str(e))

        # If blocking failure and configured to block, raise
        if gate_result.blocking and settings.block_on_failure:
            raise ValueError(
                f"Quality gate blocked workflow: {gate_result.checks_failed} check(s) failed"
            )

        logger.info(
            "quality_gate_complete",
            status=gate_result.status,
            checks_run=gate_result.checks_run,
            checks_passed=gate_result.checks_passed,
            checks_failed=gate_result.checks_failed,
        )

        return {
            "quality_gate_status": gate_result.status,
            "quality_gate_details": gate_result.to_details(),
            "quality_gate_blocking": gate_result.blocking,
            # Add field for DecisionEngine to detect blocking
            "quality_gate_blocked": gate_result.blocking,
            "blocking_reason": self._get_blocking_reason(gate_result) if gate_result.blocking else None
        }

    def _get_blocking_reason(self, gate_result) -> str:
        """Extract blocking reason from failed checks."""
        blocking_checks = [
            r for r in gate_result.results
            if r.blocking and r.status.value == "failed"
        ]

        if not blocking_checks:
            return "Quality gate blocked workflow"

        # Return first blocking check's message
        return blocking_checks[0].message
