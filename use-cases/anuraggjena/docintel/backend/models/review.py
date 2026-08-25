from sqlalchemy import Column, String, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, TimestampMixin, UUIDMixin


class Review(Base, UUIDMixin, TimestampMixin):
    """
    Review session for workflow output.

    Groups claims together for review and tracks overall review status.
    """
    __tablename__ = "reviews"

    # Foreign keys
    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)

    # Review metadata
    status = Column(String, nullable=False, default="in_review")  # in_review, approved, rejected
    reviewer_id = Column(String, nullable=True)  # User ID of reviewer
    notes = Column(Text, nullable=True)  # Review notes/comments

    # Relationships
    workflow_run = relationship("WorkflowRun", back_populates="reviews")
    workspace = relationship("Workspace")
    claims = relationship("Claim", back_populates="review", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_reviews_workspace_status", "workspace_id", "status"),
    )
