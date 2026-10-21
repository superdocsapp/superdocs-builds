from typing import Any, Dict, Optional
from uuid import UUID

from backend.repositories.audit import AuditRepository
from backend.models.audit import AuditLog
from backend.logging_config import get_logger

logger = get_logger(__name__)


class AuditService:
    """Records business events to the audit log."""

    def __init__(self, repository: AuditRepository):
        self.repository = repository

    async def log(
        self,
        event_type: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        entry = await self.repository.create(
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            details=details or {}
        )
        logger.info(
            "audit_event_logged",
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id
        )
        return entry

    async def log_workflow_started(self, run_id: str, workspace_id: str, workflow_type: str, actor_id: Optional[str] = None) -> AuditLog:
        return await self.log(
            event_type="workflow.started",
            resource_type="workflow_run",
            resource_id=run_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            details={"workflow_type": workflow_type}
        )

    async def log_workflow_completed(self, run_id: str, workspace_id: str, status: str) -> AuditLog:
        return await self.log(
            event_type="workflow.completed",
            resource_type="workflow_run",
            resource_id=run_id,
            workspace_id=workspace_id,
            details={"status": status}
        )

    async def log_review_created(self, review_id: str, workspace_id: str, actor_id: Optional[str] = None) -> AuditLog:
        return await self.log(
            event_type="review.created",
            resource_type="review",
            resource_id=review_id,
            workspace_id=workspace_id,
            actor_id=actor_id
        )

    async def log_review_completed(self, review_id: str, workspace_id: str, status: str, actor_id: Optional[str] = None) -> AuditLog:
        return await self.log(
            event_type="review.completed",
            resource_type="review",
            resource_id=review_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            details={"status": status}
        )

    async def log_export_created(self, export_id: str, workspace_id: str, format: str, actor_id: Optional[str] = None) -> AuditLog:
        return await self.log(
            event_type="export.created",
            resource_type="export",
            resource_id=export_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            details={"format": format}
        )

    async def get_workspace_audit_log(self, workspace_id: UUID, event_type: Optional[str] = None, limit: int = 100):
        return await self.repository.list_by_workspace(workspace_id, event_type, limit)

    async def get_resource_audit_log(self, resource_type: str, resource_id: str, limit: int = 50):
        return await self.repository.list_by_resource(resource_type, resource_id, limit)
