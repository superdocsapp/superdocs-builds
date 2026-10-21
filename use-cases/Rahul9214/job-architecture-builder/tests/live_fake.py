"""Protocol fake for live orchestration tests. No HTTP, no live credentials."""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO, Sequence

from job_architecture.superdocs.errors import SuperDocsError
from job_architecture.superdocs.models import (
    ApprovalResult,
    AsyncJobHandle,
    DocumentRef,
    ExportRequest,
    ExportResult,
    JobSnapshot,
    ProposedChange,
    ReviewDecision,
    SavedDocument,
    SearchAccepted,
    SessionRoster,
    SuperDocsSettings,
    TemplateRef,
    UploadResult,
)

OFFLINE_API_KEY = "sk_test_offline_not_a_real_key"


class FakeProtocolClient:
    """In-memory SuperDocsClientProtocol used by Phase 7A offline tests."""

    def __init__(self) -> None:
        self.settings = SuperDocsSettings(api_key=OFFLINE_API_KEY, base_url="https://api.superdocs.app")
        self.calls: list[str] = []
        self.uploads: list[str] = []
        self.template_uploads: list[str] = []
        self.edits: list[dict[str, Any]] = []
        self.reviews: list[tuple[str, tuple[ReviewDecision, ...]]] = []
        self.continues: list[str] = []
        self.searches: list[dict[str, Any]] = []
        self.exports: list[str] = []
        self.export_requests: list[dict[str, Any]] = []
        self.documents: list[DocumentRef] = []
        self.template_refs: list[TemplateRef] = []
        self.jobs: dict[str, JobSnapshot] = {}
        self.fail_after_uploads: int | None = None
        self.fail_wait = False
        self.after_review_status = "completed"
        self.after_review_awaiting: str | None = None
        self.export_bytes = b"PK\x03\x04-fake-docx-bytes"
        self.omit_durable_on_upload = False
        self.search_job_status = "completed"
        self.complete_search_on_wait = True
        self._durable_by_doc_id: dict[str, str] = {}
        self._doc_counter = 0
        self._job_counter = 0
        self._template_counter = 0

    def upload_document(
        self,
        filename: str,
        content: bytes,
        *,
        session_id: str,
        open_mode: str = "new_focused",
        operation_key: str | None = None,
    ) -> UploadResult:
        self.calls.append("upload_document")
        if self.fail_after_uploads is not None and len(self.uploads) >= self.fail_after_uploads:
            raise SuperDocsError("forced upload failure")
        self._doc_counter += 1
        document_id = f"doc_{self._doc_counter}"
        durable = f"durable_{self._doc_counter}"
        self._durable_by_doc_id[document_id] = durable
        document = DocumentRef(
            document_id=document_id,
            durable_document_id=None if self.omit_durable_on_upload else durable,
            title=filename,
            focused=True,
            session_id=session_id,
        )
        if open_mode == "replace":
            self.documents = [document]
        else:
            self.documents.append(document)
        self.uploads.append(filename)
        if self.omit_durable_on_upload:
            roster = SessionRoster(
                session_id=session_id,
                documents=tuple(self.documents),
                focused_document_id=document.document_id,
            )
        else:
            roster = self.list_session_documents(session_id)
        return UploadResult(
            session_id=session_id,
            document=document,
            roster=roster,
            filename=filename,
            operation_key=operation_key,
        )

    def upload_template(
        self,
        filename: str,
        content: bytes,
        *,
        operation_key: str | None = None,
    ) -> TemplateRef:
        self.calls.append("upload_template")
        self._template_counter += 1
        ref = TemplateRef(
            template_id=f"tpl_{self._template_counter}",
            name=filename,
            filename=filename,
        )
        self.template_refs.append(ref)
        self.template_uploads.append(filename)
        return ref

    def list_session_documents(self, session_id: str) -> SessionRoster:
        self.calls.append("list_session_documents")
        documents = tuple(
            DocumentRef(
                document_id=item.document_id,
                durable_document_id=item.durable_document_id
                or self._durable_by_doc_id.get(item.document_id),
                title=item.title,
                focused=item.focused,
                chunks_count=item.chunks_count,
                version_id=item.version_id,
                session_id=item.session_id or session_id,
            )
            for item in self.documents
        )
        return SessionRoster(
            session_id=session_id,
            documents=documents,
            focused_document_id=documents[-1].document_id if documents else None,
        )

    def list_saved_documents(self, *, limit: int = 50, offset: int = 0) -> tuple[SavedDocument, ...]:
        self.calls.append("list_saved_documents")
        return tuple(
            SavedDocument(document_id=item.durable_document_id or item.document_id, title=item.title)
            for item in self.documents[offset : offset + limit]
        )

    def open_saved_documents(self, session_id: str, document_ids: Sequence[str]) -> SessionRoster:
        self.calls.append("open_saved_documents")
        return self.list_session_documents(session_id)

    def start_reviewed_edit(
        self,
        session_id: str,
        message: str,
        *,
        document_id: str | None = None,
        document_html: str | None = None,
        operation_key: str | None = None,
    ) -> AsyncJobHandle:
        self.calls.append("start_reviewed_edit")
        self._job_counter += 1
        job_id = f"job_{self._job_counter}"
        change = ProposedChange(
            change_id="ch_1",
            operation="edit",
            document_id=document_id,
            old_html="<p>before</p>",
            new_html="<p>after</p>",
            reason="Fill the requested section from approved architecture.",
        )
        self.jobs[job_id] = _snapshot(
            job_id,
            session_id,
            status="awaiting_approval",
            pending=(change,),
            awaiting_kind="review",
        )
        self.edits.append(
            {
                "session_id": session_id,
                "message": message,
                "document_id": document_id,
                "operation_key": operation_key,
            }
        )
        return AsyncJobHandle(
            job_id=job_id,
            session_id=session_id,
            status="queued",
            normalized_status="queued",
            operation_key=operation_key,
        )

    def get_job(self, job_id: str) -> JobSnapshot:
        self.calls.append("get_job")
        if job_id not in self.jobs:
            raise SuperDocsError(f"unknown job {job_id}")
        return self.jobs[job_id]

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float | None = None,
        max_wait_seconds: float | None = None,
        stop_on_review: bool = True,
        sleep=None,
        clock=None,
    ) -> JobSnapshot:
        self.calls.append("wait_for_job")
        if self.fail_wait:
            raise SuperDocsError("forced wait failure")
        snapshot = self.get_job(job_id)
        if (
            self.complete_search_on_wait
            and snapshot.status in {"queued", "processing"}
        ):
            snapshot = _snapshot(job_id, snapshot.session_id, status="completed", pending=(), awaiting_kind=None)
            self.jobs[job_id] = snapshot
        return snapshot

    def submit_review(
        self,
        session_id: str,
        job_id: str,
        decisions: Sequence[ReviewDecision],
        *,
        operation_key: str | None = None,
    ) -> ApprovalResult:
        self.calls.append("submit_review")
        decided = tuple(decisions)
        self.reviews.append((job_id, decided))
        self.jobs[job_id] = _snapshot(
            job_id,
            session_id,
            status=self.after_review_status,
            pending=(),
            awaiting_kind=self.after_review_awaiting,
        )
        return ApprovalResult(job_id=job_id, session_id=session_id, decided=decided)

    def continue_large_edit(
        self,
        session_id: str,
        job_id: str,
        *,
        resume: bool,
        operation_key: str | None = None,
    ) -> JobSnapshot:
        self.calls.append("continue_large_edit")
        self.continues.append(job_id)
        snapshot = _snapshot(job_id, session_id, status="completed", pending=(), awaiting_kind=None)
        self.jobs[job_id] = snapshot
        return snapshot

    def list_templates(self) -> tuple[TemplateRef, ...]:
        self.calls.append("list_templates")
        return tuple(self.template_refs)

    def search_documents(
        self,
        query: str,
        *,
        session_id: str,
        document_id: str | None = None,
        cross_session: bool = True,
        operation_key: str | None = None,
    ) -> SearchAccepted:
        self.calls.append("search_documents")
        self._job_counter += 1
        job_id = f"job_{self._job_counter}"
        self.jobs[job_id] = _snapshot(
            job_id, session_id, status=self.search_job_status, pending=(), awaiting_kind=None
        )
        accepted = SearchAccepted(
            handle=AsyncJobHandle(
                job_id=job_id,
                session_id=session_id,
                status="queued",
                normalized_status="queued",
                operation_key=operation_key,
            ),
            query=query,
        )
        self.searches.append(
            {
                "query": query,
                "session_id": session_id,
                "cross_session": cross_session,
                "operation_key": operation_key,
            }
        )
        return accepted

    def export_document(
        self,
        destination: Path | BinaryIO,
        request: ExportRequest,
        *,
        operation_key: str | None = None,
    ) -> ExportResult:
        self.calls.append("export_document")
        self.export_requests.append(request.json_body())
        if isinstance(destination, (str, Path)):
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.export_bytes)
            dest = str(path)
        else:
            destination.write(self.export_bytes)
            dest = None
        self.exports.append(dest or request.filename or "export")
        return ExportResult(
            filename=request.filename or "export.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            byte_count=len(self.export_bytes),
            destination=dest,
            operation_key=operation_key,
        )


def _snapshot(
    job_id: str,
    session_id: str,
    *,
    status: str,
    pending: tuple[ProposedChange, ...],
    awaiting_kind: str | None,
) -> JobSnapshot:
    return JobSnapshot(
        job_id=job_id,
        session_id=session_id,
        raw_status=status,
        status=status,
        progress=100 if status == "completed" else 50,
        error=None,
        pending_changes=pending,
        awaiting_kind=awaiting_kind,
        result=None,
        metadata={},
        raw={},
    )
