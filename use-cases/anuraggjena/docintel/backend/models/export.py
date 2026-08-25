from sqlalchemy import Column, String, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from backend.models.base import TimestampMixin, UUIDMixin
from backend.database import Base


class Export(Base, UUIDMixin, TimestampMixin):
    """
    Represents an exported document.

    Tracks document exports for download and audit purposes.
    """
    __tablename__ = "exports"

    # Foreign keys
    workspace_id = Column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    workflow_run_id = Column(PG_UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True, index=True)
    review_id = Column(PG_UUID(as_uuid=True), ForeignKey("reviews.id"), nullable=True, index=True)

    # Export metadata
    filename = Column(String, nullable=False)
    format = Column(String, nullable=False)  # docx, pdf, etc.
    storage_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)  # bytes

    # User tracking
    exported_by = Column(String, nullable=True)

    # Relationships
    workspace = relationship("Workspace")
    workflow_run = relationship("WorkflowRun")
    review = relationship("Review")

    # Indexes
    __table_args__ = (
        Index("ix_exports_workspace_created", "workspace_id", "created_at"),
    )
