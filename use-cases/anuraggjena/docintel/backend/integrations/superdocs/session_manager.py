"""
SuperDocs Session Manager.

Manages lifecycle of SuperDocs editing sessions and their mapping to DocIntel runs.
"""

from typing import Optional
from uuid import UUID

from backend.integrations.superdocs.client import SuperDocsClient
from backend.repositories.superdocs_session import SuperDocsSessionRepository
from backend.models.superdocs_session import SuperDocsSession
from backend.logging_config import get_logger

logger = get_logger(__name__)


class SessionManager:
    """
    Manages SuperDocs session lifecycle.

    Responsibilities:
    - Create SuperDocs sessions for workflow runs
    - Store session mappings in database
    - Close sessions on workflow completion
    - Session recovery on workflow resume
    """

    def __init__(
        self,
        superdocs_client: SuperDocsClient,
        session_repository: SuperDocsSessionRepository
    ):
        """
        Initialize session manager.

        Args:
            superdocs_client: SuperDocs API client
            session_repository: Repository for session persistence
        """
        self.client = superdocs_client
        self.repo = session_repository

    async def create_session_for_run(
        self,
        run_id: UUID,
        document_ids: Optional[list[str]] = None
    ) -> str:
        """
        Create SuperDocs session for workflow run.

        Args:
            run_id: DocIntel workflow run ID
            document_ids: Optional list of SuperDocs document IDs to open

        Returns:
            SuperDocs session ID

        Raises:
            ValueError: If session already exists for run
        """
        # Check if session already exists
        existing = await self.repo.get_by_run_id(run_id)
        if existing:
            if existing.status == "active":
                logger.info("session_already_exists", run_id=str(run_id))
                return existing.superdocs_session_id
            else:
                logger.warning(
                    "closed_session_exists_creating_new",
                    run_id=str(run_id),
                    old_session=existing.superdocs_session_id
                )

        # Create SuperDocs session
        session = await self.client.init_session(document_ids=document_ids)

        # Store mapping
        await self.repo.create_session(
            workflow_run_id=run_id,
            superdocs_session_id=session.session_id,
            superdocs_document_id=document_ids[0] if document_ids else None
        )

        logger.info(
            "session_created_for_run",
            run_id=str(run_id),
            session_id=session.session_id
        )

        return session.session_id

    async def get_session_for_run(self, run_id: UUID) -> Optional[str]:
        """
        Get SuperDocs session ID for workflow run.

        Args:
            run_id: DocIntel workflow run ID

        Returns:
            SuperDocs session ID if exists and active, None otherwise
        """
        session = await self.repo.get_by_run_id(run_id)

        if not session:
            logger.warning("no_session_for_run", run_id=str(run_id))
            return None

        if session.status != "active":
            logger.warning(
                "session_not_active",
                run_id=str(run_id),
                status=session.status
            )
            return None

        return session.superdocs_session_id

    async def update_session_document(
        self,
        run_id: UUID,
        document_id: str
    ) -> None:
        """
        Update SuperDocs document ID for session.

        Args:
            run_id: DocIntel workflow run ID
            document_id: SuperDocs document ID
        """
        await self.repo.update_document_id(run_id, document_id)

        logger.info(
            "session_document_updated",
            run_id=str(run_id),
            document_id=document_id
        )

    async def close_session(self, run_id: UUID) -> None:
        """
        Close SuperDocs session.

        Args:
            run_id: DocIntel workflow run ID
        """
        await self.repo.close_session(run_id)

        logger.info("session_closed", run_id=str(run_id))

    async def is_session_active(self, run_id: UUID) -> bool:
        """
        Check if session is active for run.

        Args:
            run_id: DocIntel workflow run ID

        Returns:
            True if active session exists, False otherwise
        """
        return await self.repo.is_session_active(run_id)

    async def get_or_create_session(
        self,
        run_id: UUID,
        document_ids: Optional[list[str]] = None
    ) -> str:
        """
        Get existing session or create new one.

        Args:
            run_id: DocIntel workflow run ID
            document_ids: Optional list of SuperDocs document IDs

        Returns:
            SuperDocs session ID
        """
        session_id = await self.get_session_for_run(run_id)

        if session_id:
            return session_id

        return await self.create_session_for_run(run_id, document_ids)
