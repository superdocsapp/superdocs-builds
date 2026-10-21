from sqlalchemy import Column, String, ForeignKey, JSON, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, UUIDMixin, TimestampMixin


class LineageLink(Base, UUIDMixin, TimestampMixin):
    """
    Explicit lineage edges between workflow entities.

    Captures relationships that cannot be derived from foreign keys:
    - Claim derived from KnowledgeEntry
    - Claim regenerated from prior Claim
    """
    __tablename__ = "lineage_links"

    # Source entity
    source_type = Column(String, nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=False)

    # Target entity
    target_type = Column(String, nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)

    # Relationship semantics
    link_type = Column(String, nullable=False)

    # Context
    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False)
    stage_name = Column(String, nullable=True)

    # Additional metadata
    link_metadata = Column("metadata", JSON, nullable=True)

    # Relationships
    workflow_run = relationship("WorkflowRun")

    __table_args__ = (
        # Composite indexes for efficient queries
        Index("ix_lineage_links_source", "source_type", "source_id"),
        Index("ix_lineage_links_target", "target_type", "target_id"),
        Index("ix_lineage_links_run", "workflow_run_id"),
        Index("ix_lineage_links_type", "link_type"),
        Index("ix_lineage_links_run_type", "workflow_run_id", "link_type"),
        # Prevent duplicate lineage edges
        UniqueConstraint("source_type", "source_id", "target_type", "target_id", "link_type", name="uq_lineage_link"),
    )
