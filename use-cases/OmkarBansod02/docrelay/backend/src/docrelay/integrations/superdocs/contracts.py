from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from docrelay.domain.enums import ProposalOperation, SuperDocsJobStatus
from docrelay.domain.write_plan import Sha256


class SuperDocsContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SessionDocumentIdentity(SuperDocsContract):
    """A session-local document identity; document_id is never valid without session_id."""

    session_id: str = Field(min_length=1, max_length=256)
    session_document_id: str = Field(min_length=1)
    durable_document_id: str | None = None


class IngestedDocument(SuperDocsContract):
    identity: SessionDocumentIdentity
    upload_version_id: str = Field(min_length=1)
    baseline_html_sha256: Sha256
    chunks_count: int = Field(ge=0)
    safe_evidence: dict[str, JsonValue] = Field(default_factory=dict)


class SessionDocument(SuperDocsContract):
    identity: SessionDocumentIdentity
    title: str | None = None
    focused: bool
    chunks_count: int | None = Field(default=None, ge=0)
    version_id: str | None = None
    html_sha256: Sha256 | None = None
    safe_evidence: dict[str, JsonValue] = Field(default_factory=dict)


class FocusedDocument(SuperDocsContract):
    identity: SessionDocumentIdentity
    focused: bool
    version_id: str | None = None
    safe_evidence: dict[str, JsonValue] = Field(default_factory=dict)


class JobReference(SuperDocsContract):
    job_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    status: SuperDocsJobStatus


class PendingChange(SuperDocsContract):
    change_id: str = Field(min_length=1)
    operation: ProposalOperation
    document_id: str = Field(min_length=1)
    chunk_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None
    insert_after_chunk_id: str | None = None
    safe_evidence: dict[str, JsonValue] = Field(default_factory=dict)


class JobSnapshot(SuperDocsContract):
    reference: JobReference
    progress: int | None = Field(default=None, ge=0, le=100)
    awaiting_kind: str | None = None
    pending_changes: tuple[PendingChange, ...] = ()
    pending_batch_decisions: dict[str, JsonValue] = Field(default_factory=dict)
    final_version_id: str | None = None
    updated_html_sha256: Sha256 | None = None
    final_change_statuses: dict[str, str] = Field(default_factory=dict)
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    error_code: str | None = None
    safe_metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ChangeReviewDecision(SuperDocsContract):
    change_id: str = Field(min_length=1)
    approved: bool
    feedback: str | None = None


class ReviewReceipt(SuperDocsContract):
    status: str = Field(min_length=1)
    batch_complete: bool
    safe_evidence: dict[str, JsonValue] = Field(default_factory=dict)


class ContinueReceipt(SuperDocsContract):
    status: str = Field(min_length=1)
    safe_evidence: dict[str, JsonValue] = Field(default_factory=dict)


class ExportArtifact(SuperDocsContract):
    docx_bytes: bytes = Field(exclude=True, min_length=1)
    sha256: Sha256
    size_bytes: int = Field(gt=0)
    content_type: str = Field(min_length=1)
    content_disposition: str | None = None
    warnings_raw: str | None = None
    warnings: tuple[dict[str, JsonValue], ...] = ()
    safe_evidence: dict[str, JsonValue] = Field(default_factory=dict)


class SuperDocsPort(Protocol):
    async def upload_docx(
        self,
        *,
        docx_bytes: bytes,
        filename: str,
        session_id: str,
        open_mode: str = "replace",
    ) -> IngestedDocument: ...

    async def list_session_documents(
        self,
        session_id: str,
        *,
        include_html: bool = False,
    ) -> tuple[SessionDocument, ...]: ...

    async def start_edit(
        self,
        *,
        target: SessionDocumentIdentity,
        instruction: str,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
    ) -> JobReference: ...

    async def get_job(self, job_id: str) -> JobSnapshot: ...

    async def recover_session_jobs(self, session_id: str) -> tuple[JobSnapshot, ...]: ...

    async def submit_decisions(
        self,
        *,
        session_id: str,
        job_id: str,
        decisions: tuple[ChangeReviewDecision, ...],
    ) -> ReviewReceipt: ...

    async def submit_continue(
        self,
        *,
        session_id: str,
        job_id: str,
        should_continue: bool,
    ) -> ContinueReceipt: ...

    async def focus_document(self, target: SessionDocumentIdentity) -> FocusedDocument: ...

    async def export_docx(
        self,
        *,
        target: SessionDocumentIdentity,
        filename: str,
    ) -> ExportArtifact: ...
