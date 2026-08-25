from sqlalchemy import Column, String, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from backend.models.base import TimestampMixin, UUIDMixin
from backend.database import Base


class AuditLog(Base, UUIDMixin, TimestampMixin):
    """Append-only audit log for significant business events."""
    __tablename__ = "audit_logs"

    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    actor_id = Column(String, nullable=True)  # user/system that triggered the event
    resource_type = Column(String, nullable=True)  # "workflow_run", "review", "export", etc.
    resource_id = Column(String, nullable=True)
    details = Column(JSON, nullable=False, default=dict)

    workspace = relationship("Workspace")

    __table_args__ = (
        Index("ix_audit_workspace_event", "workspace_id", "event_type"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )
