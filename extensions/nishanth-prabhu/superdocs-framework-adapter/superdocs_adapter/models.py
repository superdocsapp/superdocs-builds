from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ToolName(str, Enum):
    EDIT_DOCUMENT = "edit_document"
    SEARCH_DOCUMENT = "search_document"
    EXPORT_DOCUMENT = "export_document"


@dataclass(frozen=True)
class ToolResult:
    """Framework-neutral result returned by a SuperDocs tool."""

    tool: ToolName
    success: bool
    data: Any = None
    error: str | None = None

    @classmethod
    def ok(
        cls,
        tool: ToolName,
        data: Any = None,
    ) -> "ToolResult":
        return cls(
            tool=tool,
            success=True,
            data=data,
            error=None,
        )

    @classmethod
    def failure(
        cls,
        tool: ToolName,
        error: str,
    ) -> "ToolResult":
        return cls(
            tool=tool,
            success=False,
            data=None,
            error=error,
        )

    def unwrap(self) -> Any:
        """
        Return the result data or raise a framework-neutral RuntimeError.

        Framework integrations can choose to use this helper or inspect
        success/error directly.
        """
        if not self.success:
            raise RuntimeError(
                self.error or f"{self.tool.value} failed"
            )

        return self.data
