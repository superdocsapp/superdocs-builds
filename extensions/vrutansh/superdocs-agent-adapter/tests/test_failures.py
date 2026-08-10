from pathlib import Path

import pytest

from superdocs_adapter import (
    ExportFormat,
    Job,
    JobFailedError,
    JobStatus,
    JobTimeoutError,
    SuperDocsAdapter,
)
from superdocs_adapter.models import UploadResult


class TerminalClient:
    def __init__(self, status: JobStatus) -> None:
        self.status = status

    def upload_document(self, *_: object) -> UploadResult:
        return UploadResult("session-1", "document-1")

    def start_edit(self, *_: object, **__: object) -> str:
        return "job-1"

    def get_job(self, *_: object, **__: object) -> Job:
        return Job(
            "job-1",
            "session-1",
            self.status,
            20,
            error="provider failed" if self.status is JobStatus.FAILED else None,
        )


def source_file(tmp_path: Path) -> Path:
    source = tmp_path / "sample.txt"
    source.write_text("Sample", encoding="utf-8")
    return source


def test_failed_job_surfaces_server_cause(tmp_path: Path) -> None:
    adapter = SuperDocsAdapter(TerminalClient(JobStatus.FAILED))  # type: ignore[arg-type]

    with pytest.raises(JobFailedError, match="provider failed"):
        adapter.edit_and_export(source_file(tmp_path), "Edit exactly one sentence")


def test_timeout_tells_caller_to_resume_checkpoint(tmp_path: Path) -> None:
    adapter = SuperDocsAdapter(
        TerminalClient(JobStatus.IN_PROGRESS),  # type: ignore[arg-type]
        timeout=0,
    )

    with pytest.raises(JobTimeoutError, match="same checkpoint to resume"):
        adapter.edit_and_export(
            source_file(tmp_path),
            "Edit exactly one sentence",
            export_format=ExportFormat.TXT,
            checkpoint_path=tmp_path / "run.json",
        )
