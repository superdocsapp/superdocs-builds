from pathlib import Path

from superdocs_adapter.bindings.crewai import create_flow
from superdocs_adapter.bindings.langgraph import create_workflow
from superdocs_adapter.bindings.openai_agents import create_agent
from superdocs_adapter.models import EditResult, ExportedDocument, ExportFormat
from superdocs_adapter.tools import SuperDocsToolset


class StubAdapter:
    def edit_and_export(self, *_: object, **__: object) -> EditResult:
        return EditResult(
            session_id="session-1",
            document_id="document-1",
            job_id="job-1",
            approved_change_ids=("change-1",),
            export=ExportedDocument(b"same", ExportFormat.TXT, "superdocs-output.txt"),
        )


def arguments(source: Path) -> dict[str, str]:
    return {
        "file_path": str(source),
        "instruction": "Make one exact edit",
        "output_format": "txt",
    }


def test_langgraph_quickstart_uses_compiled_state_graph(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Sample", encoding="utf-8")
    toolset = SuperDocsToolset(StubAdapter(), output_directory=tmp_path / "langgraph")  # type: ignore[arg-type]
    graph = create_workflow(toolset)

    result = graph.invoke({"arguments": arguments(source)})

    assert result["result"]["status"] == "completed"
    assert "edit_document" in graph.nodes


def test_crewai_quickstart_uses_native_flow(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Sample", encoding="utf-8")
    toolset = SuperDocsToolset(StubAdapter(), output_directory=tmp_path / "crewai")  # type: ignore[arg-type]
    flow = create_flow(toolset, arguments(source))

    result = flow.kickoff()

    assert result["status"] == "completed"
    assert flow.state["result"] == result


def test_openai_quickstart_attaches_function_tool_to_agent(tmp_path: Path) -> None:
    toolset = SuperDocsToolset(StubAdapter(), output_directory=tmp_path / "openai")  # type: ignore[arg-type]
    agent = create_agent(toolset)

    assert agent.name == "SuperDocs document editor"
    assert [tool.name for tool in agent.tools] == ["superdocs_edit_document"]
