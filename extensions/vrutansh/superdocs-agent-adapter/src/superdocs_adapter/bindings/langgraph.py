"""LangGraph/LangChain binding. Framework logic intentionally stays here."""

from __future__ import annotations

from typing import Any, Mapping

from superdocs_adapter.tools import SuperDocsToolset


def create_tools(toolset: SuperDocsToolset) -> list[Any]:
    """Return LangChain StructuredTools ready for a LangGraph ToolNode."""
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError(
            "Install the LangGraph binding with: pip install 'superdocs-agent-adapter[langgraph]'"
        ) from exc

    tools = []
    for spec in toolset.specs():
        tools.append(
            StructuredTool.from_function(
                func=spec.handler,
                name=spec.name,
                description=spec.description,
            )
        )
    return tools


def create_tool_node(toolset: SuperDocsToolset) -> Any:
    """Return a prebuilt LangGraph ToolNode using the shared core."""
    try:
        from langgraph.prebuilt import ToolNode
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError(
            "Install the LangGraph binding with: pip install 'superdocs-agent-adapter[langgraph]'"
        ) from exc
    return ToolNode(create_tools(toolset))


def invoke(toolset: SuperDocsToolset, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Invoke through LangChain's native tool boundary for a deterministic quickstart."""
    return create_tools(toolset)[0].invoke(dict(arguments))
