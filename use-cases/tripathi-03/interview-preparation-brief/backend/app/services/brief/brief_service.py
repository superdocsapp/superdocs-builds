"""Brief lifecycle: start generation, poll status, fetch result."""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.exceptions import BriefNotFoundError, SessionNotFoundError, http_not_found
from app.core.logging import get_logger
from app.models.brief import Brief
from app.models.document import IngestSession
from app.schemas.brief import (
    BriefContent,
    BriefResponse,
    BriefStatus,
    BriefStatusResponse,
)
from app.schemas.document import DocumentSource

logger = get_logger(__name__)


class BriefService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def start_generation(self, session_id: UUID) -> BriefStatusResponse:
        session = await self._get_session(session_id)
        brief = Brief(
            id=uuid.uuid4(),
            session_id=session.id,
            status=BriefStatus.PENDING.value,
            current_step="queued",
        )
        self.db.add(brief)
        await self.db.commit()
        await self.db.refresh(brief)
        logger.info("Created brief=%s for session=%s", brief.id, session_id)
        return BriefStatusResponse(
            brief_id=brief.id,
            session_id=session.id,
            status=BriefStatus.PENDING,
            current_step=brief.current_step,
        )

    async def get_brief(self, brief_id: UUID) -> BriefResponse:
        brief = await self._get_brief(brief_id, with_session=True)
        content = None
        if brief.content:
            content = BriefContent.model_validate(brief.content)
        return BriefResponse(
            brief_id=brief.id,
            session_id=brief.session_id,
            status=BriefStatus(brief.status),
            company_name=brief.session.company_name,
            content=content,
            created_at=brief.created_at,
            updated_at=brief.updated_at,
        )

    async def get_status(self, brief_id: UUID) -> BriefStatusResponse:
        brief = await self._get_brief(brief_id)
        return BriefStatusResponse(
            brief_id=brief.id,
            session_id=brief.session_id,
            status=BriefStatus(brief.status),
            current_step=brief.current_step,
            error=brief.error,
        )

    async def mark_running(self, brief_id: UUID, step: str) -> None:
        brief = await self._get_brief(brief_id)
        brief.status = BriefStatus.RUNNING.value
        brief.current_step = step
        await self.db.commit()

    async def mark_completed(self, brief_id: UUID, content: dict) -> None:
        brief = await self._get_brief(brief_id)
        brief.status = BriefStatus.COMPLETED.value
        brief.current_step = "completed"
        brief.content = content
        brief.error = None
        await self.db.commit()

    async def mark_failed(self, brief_id: UUID, error: str) -> None:
        brief = await self._get_brief(brief_id)
        brief.status = BriefStatus.FAILED.value
        brief.current_step = "failed"
        brief.error = error
        await self.db.commit()

    async def load_graph_inputs(self, session_id: UUID) -> dict:
        session = await self._get_session(session_id, with_documents=True)
        resume = next(
            (d for d in session.documents if d.source == DocumentSource.RESUME.value),
            None,
        )
        jd = next(
            (d for d in session.documents if d.source == DocumentSource.JD.value),
            None,
        )
        if resume is None or jd is None:
            raise SessionNotFoundError("Session is missing resume or JD documents")
        return {
            "session_id": str(session.id),
            "company_name": session.company_name,
            "company_url": session.company_url,
            "resume_text": resume.content_text,
            "jd_text": jd.content_text,
            "resume_document_id": str(resume.id),
            "jd_document_id": str(jd.id),
            "evidence_fallback": self.settings.evidence_fallback,
        }

    async def _get_session(
        self,
        session_id: UUID,
        *,
        with_documents: bool = False,
    ) -> IngestSession:
        stmt = select(IngestSession).where(IngestSession.id == session_id)
        if with_documents:
            stmt = stmt.options(selectinload(IngestSession.documents))
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()
        if session is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return session

    async def _get_brief(
        self,
        brief_id: UUID,
        *,
        with_session: bool = False,
    ) -> Brief:
        stmt = select(Brief).where(Brief.id == brief_id)
        if with_session:
            stmt = stmt.options(selectinload(Brief.session))
        result = await self.db.execute(stmt)
        brief = result.scalar_one_or_none()
        if brief is None:
            raise BriefNotFoundError(f"Brief {brief_id} not found")
        return brief


def ensure_http(exc: Exception):
    if isinstance(exc, (BriefNotFoundError, SessionNotFoundError)):
        return http_not_found(exc.message)
    return exc
