from pathlib import Path
from typing import Any

from superdocs_adapter.models import EditResult, ExportFormat, ExportedDocument
from superdocs_adapter.tools import SuperDocsToolset


class StubAdapter:
    def edit_and_export(self, *_: object, **__: object) -> EditResult:
        return EditResult(
            session_id="session-1",
            document_id="document-1",
            job_id="job-1",
            approved_change_ids=("change-1",),
            export=ExportedDocument(b"Same output", ExportFormat.TXT, "superdocs-output.txt"),
            final_result={"response": "done"},
        )


def test_toolset_has_portable_json_schema_and_canonical_output(tmp_path: Path) -> None:
    toolset = SuperDocsToolset(StubAdapter(), output_directory=tmp_path)  # type: ignore[arg-type]
    spec = toolset.specs()[0]

    assert spec.name == "superdocs_edit_document"
    assert spec.parameters["additionalProperties"] is False
    result = spec.handler("sample.txt", "Make the required edit", "txt")

    assert result == {
        "status": "completed",
        "approved_changes": 1,
        "export_format": "txt",
        "filename": "superdocs-output.txt",
        "size_bytes": 11,
        "output_path": (tmp_path / "superdocs-output.txt").as_posix(),
    }
    assert (tmp_path / "superdocs-output.txt").read_bytes() == b"Same output"
