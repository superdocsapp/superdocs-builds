"""SuperDocs session model."""

from sqlalchemy import Column, String, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, UUIDMixin, TimestampMixin


class SuperDocsSession(Base, UUIDMixin, TimestampMixin):
    """
    SuperDocs session mapping.

    Links DocIntel workflow runs to SuperDocs editing sessions.
    """
    __tablename__ = "superdocs_sessions"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", name="uq_superdocs_sessions_run"),
        Index("idx_superdocs_sessions_run", "workflow_run_id"),
        Index("idx_superdocs_sessions_status", "status"),
        Index("idx_superdocs_sessions_session_id", "superdocs_session_id"),
    )

    # Foreign keys
    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)

    # SuperDocs identifiers
    superdocs_session_id = Column(String(256), nullable=False)
    superdocs_document_id = Column(String(256), nullable=True)

    # Session status
    status = Column(String(50), nullable=False, default="active")

    # Lifecycle timestamps
    closed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    workflow_run = relationship("WorkflowRun", back_populates="superdocs_session")
