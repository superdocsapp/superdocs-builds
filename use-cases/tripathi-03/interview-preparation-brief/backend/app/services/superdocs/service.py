"""Orchestrate Interview Prep Brief → SuperDocs (upload/chat/approve/export)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, BriefNotFoundError, LLMConfigurationError
from app.core.logging import get_logger
from app.services.report.exporters.html_exporter import to_html
from app.services.report.service import InterviewReportService
from app.services.superdocs.client import DEFAULT_POLISH_INSTRUCTION, SuperDocsClient

logger = get_logger(__name__)


class SuperDocsBriefService:
    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        if not self.settings.superdocs_ready:
            raise LLMConfigurationError(
                "SuperDocs is disabled or SUPERDOCS_API_KEY is missing. "
                "Set SUPERDOCS_ENABLED=true and SUPERDOCS_API_KEY in .env."
            )
        self.client = SuperDocsClient(self.settings)
        self.reports = InterviewReportService(db=db, settings=self.settings)

    def _session_id_for_brief(self, brief_id: UUID) -> str:
        # SuperDocs session_id pattern: ^[a-zA-Z0-9_\-\.]+$
        return f"ipb-{brief_id.hex}-{uuid4().hex[:8]}"

    async def start_polish(
        self,
        brief_id: UUID,
        *,
        instruction: str | None = None,
        approval_mode: str = "ask_every_time",
    ) -> dict[str, Any]:
        """
        Build local report HTML → SuperDocs upload → async chat with HITL.
        Returns session_id + job_id for polling / approve / export.
        """
        try:
            report = await self.reports.generate_from_brief(brief_id)
        except BriefNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BriefNotFoundError(str(exc)) from exc

        html = to_html(report)
        session_id = self._session_id_for_brief(brief_id)
        company = report.cover_page.company_name.replace(" ", "-")[:40] or "company"
        filename = f"interview-prep-{company}.html"

        upload = await self.client.upload_document(
            session_id=session_id,
            filename=filename,
            content=html.encode("utf-8"),
            content_type="text/html; charset=utf-8",
        )

        # Prefer uploaded HTML from SuperDocs (chunk IDs) when present
        document_html = upload.get("html") or html
        message = (instruction or DEFAULT_POLISH_INSTRUCTION).strip()

        job = await self.client.chat_async(
            session_id=session_id,
            message=message,
            document_html=document_html,
            approval_mode=approval_mode,
        )
        job_id = job.get("job_id")
        if not job_id:
            raise AppError(f"SuperDocs chat/async returned no job_id: {job}")

        logger.info(
            "SuperDocs polish started brief=%s session=%s job=%s",
            brief_id,
            session_id,
            job_id,
        )
        return {
            "brief_id": str(brief_id),
            "session_id": session_id,
            "job_id": job_id,
            "status": "started",
            "approval_mode": approval_mode,
            "upload": {
                "filename": upload.get("filename") or filename,
                "chunks_count": upload.get("chunks_count"),
            },
            "message": (
                "Document uploaded to SuperDocs and polish job started. "
                "Poll status, approve changes, then export."
            ),
        }

    async def job_status(self, job_id: str) -> dict[str, Any]:
        job = await self.client.get_job(job_id)
        status = job.get("status") or "unknown"
        pending = job.get("pending_changes") or []
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        return {
            "job_id": job_id,
            "status": status,
            "pending_changes": pending,
            "pending_count": len(pending),
            "ai_response": (result or {}).get("response") or job.get("response"),
            "raw_metadata_keys": list((job.get("metadata") or {}).keys())
            if isinstance(job.get("metadata"), dict)
            else [],
        }

    async def approve_changes(
        self,
        *,
        session_id: str,
        job_id: str,
        approved: bool,
        change_decisions: list[dict[str, Any]] | None = None,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        result = await self.client.approve(
            session_id=session_id,
            job_id=job_id,
            approved=approved,
            changes=change_decisions,
            feedback=feedback,
        )
        return {
            "session_id": session_id,
            "job_id": job_id,
            "approved": approved,
            "result": result,
            "message": "Approval submitted to SuperDocs. Poll job status until completed.",
        }

    async def export(
        self,
        *,
        session_id: str,
        format: str = "docx",
        filename: str | None = None,
    ) -> tuple[bytes, str, str]:
        fmt = format.lower().strip()
        if fmt not in {"docx", "pdf", "html", "markdown", "txt"}:
            raise AppError(f"Unsupported SuperDocs export format: {format}")
        content, content_type = await self.client.export(
            session_id=session_id,
            format=fmt,
            filename=filename,
        )
        ext = "md" if fmt == "markdown" else fmt
        out_name = f"{filename or 'interview-preparation-brief'}.{ext}"
        return content, content_type, out_name
