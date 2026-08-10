from __future__ import annotations

import json
from pathlib import Path

import pytest

from superdocs_adapter import (
    ConfigurationError,
    ExportFormat,
    FileCheckpointStore,
    InvalidResponseError,
    Job,
    JobStatus,
    RunCheckpoint,
    RunPhase,
    SuperDocsAdapter,
)
from superdocs_adapter.checkpoints import CHECKPOINT_VERSION, operation_fingerprint
from superdocs_adapter.models import ExportedDocument, ProposedChange, UploadResult


class CompletingClient:
    def __init__(self) -> None:
        self.upload_calls = 0
        self.start_calls = 0
        self.approval_calls = 0
        self.export_calls = 0
        self.jobs = iter(
            [
                Job("job-1", "session-1", JobStatus.AWAITING_APPROVAL, 60),
                Job(
                    "job-1",
                    "session-1",
                    JobStatus.AWAITING_APPROVAL,
                    60,
                    (ProposedChange("change-1"),),
                ),
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

    def upload_document(self, *_: object) -> UploadResult:
        self.upload_calls += 1
        return UploadResult("session-1", "document-1")

    def start_edit(self, *_: object, **__: object) -> str:
        self.start_calls += 1
        return "job-1"

    def list_session_jobs(self, *_: object, **__: object) -> tuple[Job, ...]:
        return ()

    def get_job(self, *_: object, **__: object) -> Job:
        return next(self.jobs)

    def approve_changes(self, *_: object, **__: object) -> None:
        self.approval_calls += 1

    def export_document(self, *_: object, **__: object) -> ExportedDocument:
        self.export_calls += 1
        return ExportedDocument(b"updated", ExportFormat.TXT, "result.txt")


class ResumeCompletedClient(CompletingClient):
    def __init__(self) -> None:
        super().__init__()
        self.jobs = iter(
            [
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


def test_completed_checkpoint_reexports_without_repeating_billable_work(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Original", encoding="utf-8")
    checkpoint = tmp_path / "run.json"

    first_client = CompletingClient()
    first = SuperDocsAdapter(first_client, poll_interval=0, sleep=lambda _: None)  # type: ignore[arg-type]
    first_result = first.edit_and_export(
        source,
        "Make one exact edit",
        checkpoint_path=checkpoint,
    )

    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["phase"] == "completed"
    assert "api_key" not in json.dumps(saved).lower()
    assert "Original" not in json.dumps(saved)
    assert first_result.resumed is False

    resume_client = ResumeCompletedClient()
    resumed = SuperDocsAdapter(resume_client, poll_interval=0, sleep=lambda _: None)  # type: ignore[arg-type]
    resumed_result = resumed.edit_and_export(
        source,
        "Make one exact edit",
        checkpoint_path=checkpoint,
    )

    assert resumed_result.resumed is True
    assert resumed_result.approved_change_ids == ("change-1",)
    assert resume_client.upload_calls == 0
    assert resume_client.start_calls == 0
    assert resume_client.approval_calls == 0
    assert resume_client.export_calls == 1  # exports are non-billable and safe to repeat


def test_uploaded_checkpoint_adopts_existing_session_job(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Original", encoding="utf-8")
    instruction = "Make one exact edit"
    checkpoint_path = tmp_path / "run.json"
    fingerprint = operation_fingerprint(source, instruction, ExportFormat.TXT, "core", "balanced")
    FileCheckpointStore(checkpoint_path).save(
        RunCheckpoint(
            version=CHECKPOINT_VERSION,
            fingerprint=fingerprint,
            phase=RunPhase.UPLOADED,
            session_id="session-1",
            document_id="document-1",
        )
    )

    client = CompletingClient()
    client.list_session_jobs = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        Job("job-1", "session-1", JobStatus.PENDING),
    )
    adapter = SuperDocsAdapter(client, poll_interval=0, sleep=lambda _: None)  # type: ignore[arg-type]
    result = adapter.edit_and_export(
        source,
        instruction,
        checkpoint_path=checkpoint_path,
    )

    assert result.resumed is True
    assert client.upload_calls == 0
    assert client.start_calls == 0
    assert client.approval_calls == 1


def test_checkpoint_refuses_different_inputs(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Original", encoding="utf-8")
    checkpoint = tmp_path / "run.json"
    client = CompletingClient()
    adapter = SuperDocsAdapter(client, poll_interval=0, sleep=lambda _: None)  # type: ignore[arg-type]
    adapter.edit_and_export(source, "First instruction", checkpoint_path=checkpoint)

    with pytest.raises(ConfigurationError, match="different inputs"):
        adapter.edit_and_export(source, "Different instruction", checkpoint_path=checkpoint)


@pytest.mark.parametrize(
    "payload, message",
    [
        ("not-json", "Could not read checkpoint"),
        ("[]", "must contain a JSON object"),
        ('{"version": 99}', "Unsupported checkpoint version"),
        (
            '{"version": 1, "fingerprint": "f", "phase": "uploaded", '
            '"session_id": "s", "approved_change_ids": "wrong"}',
            "malformed",
        ),
    ],
)
def test_checkpoint_corruption_has_actionable_errors(
    tmp_path: Path, payload: str, message: str
) -> None:
    checkpoint = tmp_path / "run.json"
    checkpoint.write_text(payload, encoding="utf-8")

    with pytest.raises(InvalidResponseError, match=message):
        FileCheckpointStore(checkpoint).load()
