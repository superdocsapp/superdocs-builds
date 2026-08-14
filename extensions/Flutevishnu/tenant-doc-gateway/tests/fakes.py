"""Test doubles so the whole suite runs with NO live SuperDocs key and NO Redis."""

from __future__ import annotations

import uuid

from app.integrations.superdocs.schemas import ExportResult, JobResult, UploadResult


class FakeSuperDocsClient:
    """In-memory stand-in for SuperDocsClient.

    Deterministic and offline. Behaviour is configurable per-test via attributes.
    """

    def __init__(self) -> None:
        self.upload_calls = 0
        self.chat_calls = 0
        self.decide_calls: list[dict] = []
        # By default an edit proposes two independent changes (for HITL tests).
        self.pending_changes: list[dict] = [
            {"change_id": "c1", "chunk_id": "chunk-1", "new_html": "<p>One</p>"},
            {"change_id": "c2", "chunk_id": "chunk-2", "new_html": "<p>Two</p>"},
        ]

    async def upload_document(
        self, *, file_path: str, filename: str, content_type: str, session_id: str | None = None
    ) -> UploadResult:
        self.upload_calls += 1
        sid = session_id or f"sd-sess-{uuid.uuid4().hex[:8]}"
        return UploadResult(
            document_id=f"sd-doc-{uuid.uuid4().hex[:8]}",
            session_id=sid,
            ops_cost=0.0,
        )

    async def start_chat_async(
        self,
        *,
        session_id: str,
        instruction: str,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        response_mode: str = "full",
    ) -> JobResult:
        self.chat_calls += 1
        status = "awaiting_approval" if self.pending_changes else "completed"
        return JobResult(
            job_id=f"sd-job-{uuid.uuid4().hex[:8]}",
            status=status,
            session_id=session_id,
            document_html="<p>edited</p>" if not self.pending_changes else None,
            pending_changes=list(self.pending_changes),
            ops_cost=1.0,
        )

    async def get_job(self, job_id: str) -> JobResult:
        status = "awaiting_approval" if self.pending_changes else "completed"
        return JobResult(
            job_id=job_id,
            status=status,
            document_html=None if self.pending_changes else "<p>edited</p>",
            pending_changes=list(self.pending_changes),
            ops_cost=1.0,
        )

    async def decide_change(
        self,
        *,
        session_id: str,
        job_id: str,
        change_id: str,
        approved: bool,
        feedback: str | None = None,
    ) -> JobResult:
        self.decide_calls.append(
            {
                "session_id": session_id,
                "job_id": job_id,
                "change_id": change_id,
                "approved": approved,
                "feedback": feedback,
            }
        )
        return JobResult(job_id=job_id, status="in_progress", pending_changes=[])

    async def export_document(self, *, session_id: str, fmt: str = "docx") -> ExportResult:
        return ExportResult(download_url=f"https://example.test/export.{fmt}", ops_cost=0.0)

    async def aclose(self) -> None:
        return None


class FakeQueue:
    """Records enqueues instead of talking to Redis."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue(self, task_name: str, job_id: uuid.UUID) -> None:
        self.enqueued.append(job_id)
