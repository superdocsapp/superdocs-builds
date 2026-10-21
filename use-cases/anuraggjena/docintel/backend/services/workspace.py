from uuid import UUID
from typing import List, Optional

from backend.repositories.workspace import WorkspaceRepository
from backend.models.workspace import Workspace
from backend.logging_config import get_logger

logger = get_logger(__name__)


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository):
        self.repository = repository

    async def create_workspace(
        self,
        name: str,
        owner_user_id,
        workflow_type: Optional[str] = None
    ) -> Workspace:
        """Create a new workspace"""
        logger.info("creating_workspace", name=name, owner_user_id=str(owner_user_id))

        workspace = await self.repository.create(
            name=name,
            owner_user_id=owner_user_id,
            workflow_type=workflow_type
        )

        logger.info("workspace_created", workspace_id=str(workspace.id))
        return workspace

    async def get_workspace(self, workspace_id: UUID) -> Optional[Workspace]:
        """Get workspace by ID"""
        return await self.repository.get_by_id(workspace_id)

    async def list_user_workspaces(self, owner_user_id) -> List[Workspace]:
        """List all workspaces for a user"""
        return await self.repository.list_by_owner(owner_user_id)

    async def update_workspace(
        self,
        workspace_id: UUID,
        name: Optional[str] = None,
        workflow_type: Optional[str] = None
    ) -> Optional[Workspace]:
        """Update workspace details"""
        updates = {}
        if name is not None:
            updates['name'] = name
        if workflow_type is not None:
            updates['workflow_type'] = workflow_type

        if not updates:
            return await self.get_workspace(workspace_id)

        logger.info("updating_workspace", workspace_id=str(workspace_id))
        return await self.repository.update(workspace_id, **updates)

    async def delete_workspace(self, workspace_id: UUID) -> bool:
        """Soft delete a workspace"""
        from datetime import datetime, timezone

        workspace = await self.repository.update(
            workspace_id,
            status="deleted",
            deleted_at=datetime.now(timezone.utc)
        )

        if workspace:
            logger.info("workspace_deleted", workspace_id=str(workspace_id))
            return True
        return False
