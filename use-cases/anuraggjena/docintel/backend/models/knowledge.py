from sqlalchemy import Column, String, Float, ForeignKey, JSON, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from backend.models.base import TimestampMixin, UUIDMixin
from backend.database import Base


class KnowledgeEntry(Base, UUIDMixin, TimestampMixin):
    """A stored knowledge item from a prior workflow run."""
    __tablename__ = "knowledge_entries"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    workflow_type = Column(String, nullable=False, index=True)  # e.g. "tariff"
    source_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True)
    source_document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)

    entry_type = Column(String, nullable=False)  # "claim", "summary", "full_output"
    content = Column(Text, nullable=False)
    extra_metadata = Column(JSON, nullable=False, default=dict)
    confidence_score = Column(Float, nullable=True)
    tags = Column(JSON, nullable=False, default=list)  # list of string tags

    workspace = relationship("Workspace")
    source_run = relationship("WorkflowRun")
    source_document = relationship("Document")

    __table_args__ = (
        Index("ix_knowledge_workspace_type", "workspace_id", "workflow_type"),
    )
