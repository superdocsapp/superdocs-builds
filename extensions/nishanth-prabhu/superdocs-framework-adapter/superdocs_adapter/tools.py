from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .core import SuperDocsAdapter
from .models import ToolName, ToolResult


@dataclass(frozen=True)
class ToolDefinition:
    """Framework-neutral description of a SuperDocs operation."""

    name: ToolName
    description: str
    handler: Callable[..., ToolResult]

    def execute(self, **kwargs: object) -> ToolResult:
        """Execute the underlying SuperDocs operation."""
        return self.handler(**kwargs)


def create_tool_definitions(
    adapter: SuperDocsAdapter,
) -> dict[ToolName, ToolDefinition]:
    """Create framework-neutral tool definitions for an adapter."""

    return {
        ToolName.EDIT_DOCUMENT: ToolDefinition(
            name=ToolName.EDIT_DOCUMENT,
            description="Apply an instruction-driven edit to a document.",
            handler=adapter.edit_document,
        ),
        ToolName.SEARCH_DOCUMENT: ToolDefinition(
            name=ToolName.SEARCH_DOCUMENT,
            description="Search a document for information relevant to a query.",
            handler=adapter.search_document,
        ),
        ToolName.EXPORT_DOCUMENT: ToolDefinition(
            name=ToolName.EXPORT_DOCUMENT,
            description="Export a document in the requested format.",
            handler=adapter.export_document,
        ),
    }
