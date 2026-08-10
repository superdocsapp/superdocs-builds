"""CrewAI binding. Framework logic intentionally stays here."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from superdocs_adapter.tools import SuperDocsToolset


def create_tools(toolset: SuperDocsToolset) -> list[Any]:
    """Return CrewAI tools without adding CrewAI to the core dependency set."""
    try:
        from crewai.tools import tool
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError(
            "Install the CrewAI binding with: pip install 'superdocs-agent-adapter[crewai]'"
        ) from exc

    spec = toolset.specs()[0]

    @tool(spec.name)
    def edit_document(
        file_path: str, instruction: str, output_format: str = "txt"
    ) -> dict[str, Any]:
        """Upload, edit, approve, export, and save a document with SuperDocs."""
        return spec.handler(file_path, instruction, output_format)

    return [edit_document]


def invoke(toolset: SuperDocsToolset, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Invoke through CrewAI's native tool boundary for a deterministic quickstart."""
    return create_tools(toolset)[0].run(**dict(arguments))


def create_flow(toolset: SuperDocsToolset, arguments: Mapping[str, Any]) -> Any:
    """Create a deterministic CrewAI Flow that executes the shared native tool."""
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    try:
        from crewai.flow.flow import Flow, start
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError(
            "Install the CrewAI binding with: pip install 'superdocs-agent-adapter[crewai]'"
        ) from exc

    native_tool = create_tools(toolset)[0]
    initial = {"arguments": dict(arguments), "result": None}

    class SuperDocsFlow(Flow):
        @start()
        def edit_document(self) -> dict[str, Any]:
            result = native_tool.run(**self.state["arguments"])
            self.state["result"] = result
            return result

    return SuperDocsFlow(initial_state=initial, tracing=False, suppress_flow_events=True)
