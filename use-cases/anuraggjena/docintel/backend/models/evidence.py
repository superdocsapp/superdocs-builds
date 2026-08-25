from sqlalchemy import Column, String, Text, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, UUIDMixin, TimestampMixin


class Evidence(Base, UUIDMixin, TimestampMixin):
    """
    A piece of evidence extracted from a document chunk during the RetrieveStage.
    Links a workflow run to the specific document chunk that supported it.
    """
    __tablename__ = "evidence"

    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("document_chunks.id"), nullable=True, index=True)

    extracted_text = Column(Text, nullable=False)
    evidence_type = Column(String, nullable=False, default="retrieved_chunk")
    page_number = Column(String, nullable=True)
    relevance_score = Column(Float, nullable=True)

    workflow_run = relationship("WorkflowRun")
    document = relationship("Document")
    chunk = relationship("DocumentChunk")
    citations = relationship("Citation", back_populates="evidence", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_evidence_run_document", "workflow_run_id", "document_id"),
    )


class Citation(Base, UUIDMixin, TimestampMixin):
    """
    Many-to-many bridge between a Claim and an Evidence item.
    Created during CitationBuilderStage.
    """
    __tablename__ = "citations"

    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id"), nullable=False, index=True)
    evidence_id = Column(UUID(as_uuid=True), ForeignKey("evidence.id"), nullable=False, index=True)

    excerpt = Column(Text, nullable=True)
    relevance_score = Column(Float, nullable=True)

    claim = relationship("Claim")
    evidence = relationship("Evidence", back_populates="citations")

    __table_args__ = (
        Index("ix_citations_claim_evidence", "claim_id", "evidence_id"),
    )
