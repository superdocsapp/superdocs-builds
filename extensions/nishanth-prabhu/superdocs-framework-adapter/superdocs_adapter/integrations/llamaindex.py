from __future__ import annotations

from typing import Any

from ..models import ToolName, ToolResult
from ..tools import ToolDefinition


def create_llamaindex_tools(
    tools: dict[ToolName, ToolDefinition],
) -> list[Any]:
    """
    Convert framework-neutral SuperDocs tools into LlamaIndex tools.

    LlamaIndex is imported lazily so it remains an optional dependency.
    """

    try:
        from llama_index.core.tools import FunctionTool
    except ImportError as exc:
        raise ImportError(
            "LlamaIndex integration requires 'llama-index-core'. "
            "Install it with: pip install llama-index-core"
        ) from exc

    llamaindex_tools: list[Any] = []

    for definition in tools.values():

        tool = FunctionTool.from_defaults(
            fn=definition.handler,
            name=definition.name.value,
            description=definition.description,
        )

        llamaindex_tools.append(tool)

    return llamaindex_tools
