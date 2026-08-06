"""Shared LangGraph node contract: Input → Validation → Run → Output Validation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.agents.state import BriefState
from app.core.logging import get_logger

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)

logger = get_logger(__name__)


class NodeValidationError(ValueError):
    """Raised when a node input or output fails validation."""


class BaseNode(ABC, Generic[InputT, OutputT]):
    """
    Every workflow node must:
    1. Build typed input from shared state
    2. Validate input
    3. Execute
    4. Validate output
    5. Merge output into shared state
    """

    name: str
    input_model: type[InputT]
    output_model: type[OutputT]

    def validate_input(self, payload: dict[str, Any]) -> InputT:
        try:
            return self.input_model.model_validate(payload)
        except ValidationError as exc:
            raise NodeValidationError(
                f"[{self.name}] invalid input: {exc}"
            ) from exc

    def validate_output(self, payload: dict[str, Any] | OutputT) -> OutputT:
        try:
            if isinstance(payload, self.output_model):
                return payload
            return self.output_model.model_validate(payload)
        except ValidationError as exc:
            raise NodeValidationError(
                f"[{self.name}] invalid output: {exc}"
            ) from exc

    @abstractmethod
    def build_input(self, state: BriefState) -> dict[str, Any]:
        """Extract this node's input fields from shared graph state."""

    @abstractmethod
    async def execute(self, node_input: InputT, state: BriefState) -> OutputT:
        """Run node logic. Must not invent resume evidence."""

    @abstractmethod
    def merge_output(self, state: BriefState, node_output: OutputT) -> BriefState:
        """Write validated output back into shared state."""

    async def __call__(self, state: BriefState) -> BriefState:
        logger.info("▶ %s starting", self.name)
        raw_input = self.build_input(state)
        node_input = self.validate_input(raw_input)
        raw_output = await self.execute(node_input, state)
        node_output = self.validate_output(raw_output)
        updated = self.merge_output(state, node_output)
        updated["current_step"] = self.name
        updated["error"] = None
        logger.info("✔ %s completed", self.name)
        return updated
