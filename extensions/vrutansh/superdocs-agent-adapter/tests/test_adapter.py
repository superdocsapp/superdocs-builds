from pathlib import Path

from superdocs_adapter.adapter import SuperDocsAdapter
from superdocs_adapter.models import (
    ExportedDocument,
    ExportFormat,
    Job,
    JobStatus,
    ProposedChange,
    UploadResult,
)


class FakeClient:
    def __init__(self) -> None:
        self.jobs = iter(
            [
                Job("job-1", "session-1", JobStatus.IN_PROGRESS, 25),
                Job("job-1", "session-1", JobStatus.AWAITING_APPROVAL, 60),
                Job(
                    "job-1",
                    "session-1",
                    JobStatus.AWAITING_APPROVAL,
                    60,
                    (ProposedChange("change-1", "chunk-1", {"after": "New"}),),
                ),
                Job("job-1", "session-1", JobStatus.IN_PROGRESS, 80),
                Job("job-1", "session-1", JobStatus.COMPLETED, 100),
                Job(
                    "job-1",
                    "session-1",
                    JobStatus.COMPLETED,
                    100,
                    result={"response": "done"},
                ),
            ]
        )
        self.approved = []

    def upload_document(self, file_path: Path, session_id: str) -> UploadResult:
        return UploadResult("session-1", "document-1", "Sample")

    def start_edit(self, session_id: str, instruction: str, **_: str) -> str:
        return "job-1"

    def get_job(self, job_id: str, *, compact: bool = True) -> Job:
        return next(self.jobs)

    def approve_changes(self, session_id: str, job: Job, *, approved: bool = True) -> None:
        self.approved.extend(change.change_id for change in job.proposed_changes)

    def export_document(self, session_id: str, **_: object) -> ExportedDocument:
        return ExportedDocument(b"Updated document", ExportFormat.TXT, "result.txt", "text/plain")


def test_adapter_runs_four_call_contract_and_returns_canonical_result(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Old document", encoding="utf-8")
    client = FakeClient()
    adapter = SuperDocsAdapter(client, poll_interval=0, sleep=lambda _: None)  # type: ignore[arg-type]

    result = adapter.edit_and_export(source, "Replace Old with New")

    assert client.approved == ["change-1"]
    assert result.approved_change_ids == ("change-1",)
    assert result.final_result == {"response": "done"}
    assert result.canonical() == {
        "status": "completed",
        "approved_changes": 1,
        "export_format": "txt",
        "filename": "result.txt",
        "size_bytes": 16,
        "resumed": False,
    }
