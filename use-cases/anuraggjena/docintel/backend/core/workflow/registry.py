from typing import Dict, Optional, Type, List
from backend.core.workflow.runner import WorkflowRunner
from backend.core.workflow.stage import StageNode, TState
from backend.logging_config import get_logger

logger = get_logger(__name__)


class WorkflowRegistry:
    """
    Central registry for workflow definitions.

    Responsibilities:
    - Register workflow builders
    - Retrieve workflow configurations
    - List available workflows
    - Validate workflow definitions
    """

    def __init__(self):
        self._workflows: Dict[str, dict] = {}

    def register(
        self,
        workflow_name: str,
        stages: List[StageNode],
        edges: List[tuple[str, str]],
        state_schema: Type[TState],
        description: str = "",
        configuration_schema: Optional[dict] = None
    ) -> None:
        """
        Register a workflow definition.

        Args:
            workflow_name: Unique workflow identifier
            stages: List of stage nodes
            edges: List of (from_stage, to_stage) edges
            state_schema: Pydantic model for workflow state
            description: Human-readable description
            configuration_schema: JSON schema for workflow configuration
        """
        if workflow_name in self._workflows:
            logger.warning("workflow_already_registered", workflow=workflow_name)
            raise ValueError(f"Workflow '{workflow_name}' is already registered")

        # Validate workflow definition
        self._validate_workflow(workflow_name, stages, edges)

        self._workflows[workflow_name] = {
            "name": workflow_name,
            "stages": stages,
            "edges": edges,
            "state_schema": state_schema,
            "description": description,
            "configuration_schema": configuration_schema or {}
        }

        logger.info("workflow_registered", workflow=workflow_name, stage_count=len(stages))

    def get(self, workflow_name: str) -> Optional[dict]:
        """Get workflow definition by name"""
        return self._workflows.get(workflow_name)

    def list_workflows(self) -> List[dict]:
        """List all registered workflows"""
        return [
            {
                "name": wf["name"],
                "description": wf["description"],
                "stage_count": len(wf["stages"]),
                "stages": [s.name for s in wf["stages"]]
            }
            for wf in self._workflows.values()
        ]

    def create_runner(
        self,
        workflow_name: str,
        stage_repository
    ) -> WorkflowRunner:
        """
        Create a WorkflowRunner instance for a registered workflow.

        Args:
            workflow_name: Name of registered workflow
            stage_repository: WorkflowStageRepository instance

        Returns:
            Configured WorkflowRunner instance
        """
        workflow_def = self.get(workflow_name)

        if not workflow_def:
            raise ValueError(f"Workflow '{workflow_name}' not found in registry")

        return WorkflowRunner(
            workflow_name=workflow_def["name"],
            stages=workflow_def["stages"],
            edges=workflow_def["edges"],
            state_schema=workflow_def["state_schema"],
            stage_repository=stage_repository
        )

    def unregister(self, workflow_name: str) -> bool:
        """Remove a workflow from registry"""
        if workflow_name in self._workflows:
            del self._workflows[workflow_name]
            logger.info("workflow_unregistered", workflow=workflow_name)
            return True
        return False

    def _validate_workflow(
        self,
        workflow_name: str,
        stages: List[StageNode],
        edges: List[tuple[str, str]]
    ) -> None:
        """Validate workflow definition"""
        if not stages:
            raise ValueError(f"Workflow '{workflow_name}' must have at least one stage")

        if not edges:
            raise ValueError(f"Workflow '{workflow_name}' must have at least one edge")

        # Validate stage names are unique
        stage_names = [s.name for s in stages]
        if len(stage_names) != len(set(stage_names)):
            raise ValueError(f"Workflow '{workflow_name}' has duplicate stage names")

        # Validate edges reference valid stages
        stage_name_set = set(stage_names)
        for from_stage, to_stage in edges:
            if from_stage not in stage_name_set:
                raise ValueError(f"Edge references unknown stage: {from_stage}")
            if to_stage != "END" and to_stage not in stage_name_set:
                raise ValueError(f"Edge references unknown stage: {to_stage}")

        # Validate there's an entry point (at least one stage with no incoming edges)
        all_stage_names = set(stage_names)
        to_stages = {edge[1] for edge in edges if edge[1] != "END"}
        entry_points = all_stage_names - to_stages

        if not entry_points:
            raise ValueError(
                f"Workflow '{workflow_name}' has no entry point. "
                f"All stages have incoming edges: {sorted(all_stage_names)}"
            )


# Global registry instance
workflow_registry = WorkflowRegistry()
