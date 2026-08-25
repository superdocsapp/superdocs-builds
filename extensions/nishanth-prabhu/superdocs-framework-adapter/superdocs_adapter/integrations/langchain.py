from __future__ import annotations

from typing import Any

from ..models import ToolName, ToolResult
from ..tools import ToolDefinition


def create_langchain_tools(
    tools: dict[ToolName, ToolDefinition],
) -> list[Any]:
    """
    Convert framework-neutral SuperDocs tools into LangChain tools.

    LangChain is imported lazily so the core SuperDocs adapter does not
    require LangChain as a dependency.
    """

    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise ImportError(
            "LangChain integration requires 'langchain-core'. "
            "Install it with: pip install langchain-core"
        ) from exc

    langchain_tools: list[Any] = []

    for definition in tools.values():

        tool = StructuredTool.from_function(
            func=definition.handler,
            name=definition.name.value,
            description=definition.description,
        )

        langchain_tools.append(tool)

    return langchain_tools
