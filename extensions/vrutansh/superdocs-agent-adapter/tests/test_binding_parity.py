import json
from pathlib import Path

from superdocs_adapter.bindings.crewai import invoke as invoke_crewai
from superdocs_adapter.bindings.langgraph import invoke as invoke_langgraph
from superdocs_adapter.bindings.openai_agents import invoke as invoke_openai_agents
from superdocs_adapter.models import EditResult, ExportFormat, ExportedDocument
from superdocs_adapter.tools import SuperDocsToolset


class RecordingAdapter:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def edit_and_export(self, *args: object, **kwargs: object) -> EditResult:
        self.calls.append((args, kwargs))
        return EditResult(
            session_id="normalized-away",
            document_id="normalized-away",
            job_id="normalized-away",
            approved_change_ids=("change-1",),
            export=ExportedDocument(
                self.content,
                ExportFormat.TXT,
                "superdocs-output.txt",
                "text/plain",
            ),
            final_result={"response": "done"},
        )


def test_all_framework_bindings_produce_identical_output(tmp_path: Path) -> None:
    expected = b"Customer Support Policy\n\nUpdated support hours.\n"
    arguments = {
        "file_path": "sample-policy.txt",
        "instruction": "Make the canonical edit",
        "output_format": "txt",
    }
    results = []

    for name, invoke in (
        ("langgraph", invoke_langgraph),
        ("crewai", invoke_crewai),
        ("openai_agents", invoke_openai_agents),
    ):
        adapter = RecordingAdapter(expected)
        toolset = SuperDocsToolset(adapter, output_directory=tmp_path / name)  # type: ignore[arg-type]
        result = invoke(toolset, arguments)
        output = (tmp_path / name / "superdocs-output.txt").read_bytes()
        results.append((result, output, adapter.calls))

    canonical = [json.dumps(item[0], sort_keys=True) for item in results]
    # Paths differ by quickstart, so compare the public result without the path.
    stripped = [json.loads(item) | {"output_path": "<normalized>"} for item in canonical]
    assert stripped[0] == stripped[1] == stripped[2]
    assert results[0][1] == results[1][1] == results[2][1] == expected
    assert results[0][2] == results[1][2] == results[2][2]
