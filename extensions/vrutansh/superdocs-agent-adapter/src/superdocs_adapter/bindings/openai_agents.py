"""OpenAI Agents SDK binding. Framework logic intentionally stays here."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from superdocs_adapter.tools import SuperDocsToolset


def create_tools(toolset: SuperDocsToolset) -> list[Any]:
    """Return OpenAI Agents SDK FunctionTools backed by the shared core."""
    try:
        from agents import function_tool
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError(
            "Install this binding with: pip install 'superdocs-agent-adapter[openai-agents]'"
        ) from exc

    spec = toolset.specs()[0]

    @function_tool(name_override=spec.name, description_override=spec.description)
    def edit_document(
        file_path: str, instruction: str, output_format: str = "txt"
    ) -> dict[str, Any]:
        return spec.handler(file_path, instruction, output_format)

    return [edit_document]


async def ainvoke(toolset: SuperDocsToolset, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Invoke through the Agents SDK tool boundary without an extra model call."""
    try:
        from agents.tool_context import ToolContext
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError(
            "Install this binding with: pip install 'superdocs-agent-adapter[openai-agents]'"
        ) from exc
    tool = create_tools(toolset)[0]
    encoded = json.dumps(dict(arguments))
    context = ToolContext(
        context=None,
        tool_name=tool.name,
        tool_call_id="quickstart-call",
        tool_arguments=encoded,
    )
    return await tool.on_invoke_tool(context, encoded)


def invoke(toolset: SuperDocsToolset, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Synchronous convenience wrapper for scripts outside an active event loop."""
    return asyncio.run(ainvoke(toolset, arguments))


def create_agent(toolset: SuperDocsToolset) -> Any:
    """Create an Agent with the shared FunctionTool attached; no model call is made."""
    try:
        from agents import Agent
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError(
            "Install this binding with: pip install 'superdocs-agent-adapter[openai-agents]'"
        ) from exc
    return Agent(
        name="SuperDocs document editor",
        instructions=(
            "Use the SuperDocs tool for document edits. Preserve the requested review and "
            "export workflow, and report only the tool's verified result."
        ),
        tools=create_tools(toolset),
        tool_use_behavior="stop_on_first_tool",
    )
