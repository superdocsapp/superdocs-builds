from __future__ import annotations

from typing import Any, Callable

from ..models import ToolName, ToolResult
from ..tools import ToolDefinition


LangGraphNode = Callable[[dict[str, Any]], dict[str, Any]]


def create_langgraph_nodes(
    tools: dict[ToolName, ToolDefinition],
) -> dict[str, LangGraphNode]:
    """
    Convert framework-neutral SuperDocs tools into LangGraph-compatible
    node functions.

    LangGraph itself is not required by the core adapter. A node is simply
    a callable accepting state and returning state updates.
    """

    nodes: dict[str, LangGraphNode] = {}

    for definition in tools.values():

        def node(
            state: dict[str, Any],
            definition: ToolDefinition = definition,
        ) -> dict[str, Any]:
            result = definition.execute(**state)

            return {
                "superdocs_result": result,
                "superdocs_tool": definition.name.value,
            }

        nodes[definition.name.value] = node

    return nodes


def execute_langgraph_node(
    node: LangGraphNode,
    state: dict[str, Any],
) -> ToolResult:
    """
    Execute a generated LangGraph node and extract its SuperDocs result.
    """

    updated_state = node(state)

    result = updated_state.get("superdocs_result")

    if not isinstance(result, ToolResult):
        raise TypeError(
            "LangGraph node did not return a ToolResult under "
            "'superdocs_result'."
        )

    return result
