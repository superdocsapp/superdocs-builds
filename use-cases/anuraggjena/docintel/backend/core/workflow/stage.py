from abc import ABC, abstractmethod
from typing import Any, Dict, TypeVar, Generic
from pydantic import BaseModel, ConfigDict

from backend.logging_config import get_logger

logger = get_logger(__name__)


# Base state type
TState = TypeVar('TState', bound=BaseModel)


class StageNode(ABC, Generic[TState]):
    """
    Abstract base class for workflow stage nodes.

    Each stage is a LangGraph node that processes workflow state
    and returns state updates.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def execute(self, state: TState) -> Dict[str, Any]:
        """
        Execute the stage logic and return state updates.

        Args:
            state: Current workflow state

        Returns:
            Dictionary of state updates to be merged
        """
        pass

    async def __call__(self, state: TState) -> Dict[str, Any]:
        """
        Entry point for LangGraph node execution.
        Wraps execute with logging.
        """
        logger.info("stage_started", stage=self.name)

        try:
            updates = await self.execute(state)
            logger.info("stage_completed", stage=self.name)
            return updates
        except Exception as e:
            logger.error("stage_failed", stage=self.name, error=str(e))
            raise


class WorkflowState(BaseModel):
    """Base workflow state with common fields"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workflow_run_id: str
    workspace_id: str
    document_id: str
    status: str = "pending"
    current_stage: str | None = None
    error: str | None = None
