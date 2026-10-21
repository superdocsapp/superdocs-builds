"""Application-facing SuperDocs contract. Domain code depends on this, not HTTP."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Protocol, Sequence

from job_architecture.superdocs.models import (
    ApprovalResult,
    AsyncJobHandle,
    ExportRequest,
    ExportResult,
    JobSnapshot,
    ReviewDecision,
    SavedDocument,
    SearchAccepted,
    SessionRoster,
    SuperDocsSettings,
    TemplateRef,
    UploadResult,
)


class SuperDocsClientProtocol(Protocol):
    settings: SuperDocsSettings

    def upload_document(
        self,
        filename: str,
        content: bytes,
        *,
        session_id: str,
        open_mode: str = "new_focused",
        operation_key: str | None = None,
    ) -> UploadResult: ...

    def upload_template(
        self,
        filename: str,
        content: bytes,
        *,
        operation_key: str | None = None,
    ) -> TemplateRef: ...

    def list_session_documents(self, session_id: str) -> SessionRoster: ...

    def list_saved_documents(self, *, limit: int = 50, offset: int = 0) -> tuple[SavedDocument, ...]: ...

    def open_saved_documents(self, session_id: str, document_ids: Sequence[str]) -> SessionRoster: ...

    def start_reviewed_edit(
        self,
        session_id: str,
        message: str,
        *,
        document_id: str | None = None,
        document_html: str | None = None,
        operation_key: str | None = None,
    ) -> AsyncJobHandle: ...

    def get_job(self, job_id: str) -> JobSnapshot: ...

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float | None = None,
        max_wait_seconds: float | None = None,
        stop_on_review: bool = True,
        sleep=None,
        clock=None,
    ) -> JobSnapshot: ...

    def submit_review(
        self,
        session_id: str,
        job_id: str,
        decisions: Sequence[ReviewDecision],
        *,
        operation_key: str | None = None,
    ) -> ApprovalResult: ...

    def continue_large_edit(
        self,
        session_id: str,
        job_id: str,
        *,
        resume: bool,
        operation_key: str | None = None,
    ) -> JobSnapshot: ...

    def list_templates(self) -> tuple[TemplateRef, ...]: ...

    def search_documents(
        self,
        query: str,
        *,
        session_id: str,
        document_id: str | None = None,
        cross_session: bool = True,
        operation_key: str | None = None,
    ) -> SearchAccepted: ...

    def export_document(
        self,
        destination: Path | BinaryIO,
        request: ExportRequest,
        *,
        operation_key: str | None = None,
    ) -> ExportResult: ...
