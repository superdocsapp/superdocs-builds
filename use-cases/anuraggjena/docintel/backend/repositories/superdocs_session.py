"""SuperDocs session repository."""

from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.base import BaseRepository
from backend.models.superdocs_session import SuperDocsSession
from backend.logging_config import get_logger

logger = get_logger(__name__)


class SuperDocsSessionRepository(BaseRepository[SuperDocsSession]):
    """Repository for SuperDocs session operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, SuperDocsSession)

    async def create_session(
        self,
        workflow_run_id: UUID,
        superdocs_session_id: str,
        superdocs_document_id: Optional[str] = None
    ) -> SuperDocsSession:
        """
        Create SuperDocs session mapping.

        Args:
            workflow_run_id: DocIntel workflow run ID
            superdocs_session_id: SuperDocs session ID
            superdocs_document_id: Optional SuperDocs document ID

        Returns:
            Created SuperDocsSession
        """
        session = await self.create(
            workflow_run_id=workflow_run_id,
            superdocs_session_id=superdocs_session_id,
            superdocs_document_id=superdocs_document_id,
            status="active"
        )

        logger.info(
            "superdocs_session_created",
            run_id=str(workflow_run_id),
            session_id=superdocs_session_id
        )

        return session

    async def get_by_run_id(self, workflow_run_id: UUID) -> Optional[SuperDocsSession]:
        """
        Get SuperDocs session by workflow run ID.

        Args:
            workflow_run_id: DocIntel workflow run ID

        Returns:
            SuperDocsSession if found, None otherwise
        """
        stmt = select(SuperDocsSession).where(
            SuperDocsSession.workflow_run_id == workflow_run_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_superdocs_session_id(
        self,
        superdocs_session_id: str
    ) -> Optional[SuperDocsSession]:
        """
        Get SuperDocs session by SuperDocs session ID.

        Args:
            superdocs_session_id: SuperDocs session ID

        Returns:
            SuperDocsSession if found, None otherwise
        """
        stmt = select(SuperDocsSession).where(
            SuperDocsSession.superdocs_session_id == superdocs_session_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_document_id(
        self,
        workflow_run_id: UUID,
        superdocs_document_id: str
    ) -> Optional[SuperDocsSession]:
        """
        Update SuperDocs document ID for session.

        Args:
            workflow_run_id: DocIntel workflow run ID
            superdocs_document_id: SuperDocs document ID

        Returns:
            Updated SuperDocsSession if found, None otherwise
        """
        session = await self.get_by_run_id(workflow_run_id)
        if not session:
            return None

        return await self.update(
            session.id,
            superdocs_document_id=superdocs_document_id
        )

    async def close_session(self, workflow_run_id: UUID) -> Optional[SuperDocsSession]:
        """
        Mark session as closed.

        Args:
            workflow_run_id: DocIntel workflow run ID

        Returns:
            Updated SuperDocsSession if found, None otherwise
        """
        session = await self.get_by_run_id(workflow_run_id)
        if not session:
            return None

        return await self.update(
            session.id,
            status="closed",
            closed_at=datetime.now(timezone.utc)
        )

    async def is_session_active(self, workflow_run_id: UUID) -> bool:
        """
        Check if session is active.

        Args:
            workflow_run_id: DocIntel workflow run ID

        Returns:
            True if session exists and is active, False otherwise
        """
        session = await self.get_by_run_id(workflow_run_id)
        return session is not None and session.status == "active"
