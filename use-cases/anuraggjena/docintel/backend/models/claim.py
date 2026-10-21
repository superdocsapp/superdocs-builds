from sqlalchemy import Column, String, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, TimestampMixin, UUIDMixin


class Claim(Base, UUIDMixin, TimestampMixin):
    """
    Represents a single claim extracted from a document.

    Claims are the atomic units of information that get reviewed and approved.
    For tariff workflow: HS codes, duty rates, etc.
    """
    __tablename__ = "claims"

    # Foreign keys
    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True)
    review_id = Column(UUID(as_uuid=True), ForeignKey("reviews.id"), nullable=True, index=True)

    # Claim data
    claim_type = Column(String, nullable=False)  # e.g., "tariff_code", "duty_rate"
    content = Column(Text, nullable=False)  # JSON or structured text
    status = Column(String, nullable=False, default="pending")  # pending, approved, rejected, edited

    # Edit tracking
    original_content = Column(Text, nullable=True)  # Original before edits
    edited_by = Column(String, nullable=True)  # User ID who made edits

    # Source tracking
    source_stage = Column(String, nullable=True)  # Which stage created this claim
    confidence_score = Column(String, nullable=True)  # LLM confidence if available

    # SuperDocs integration
    superdocs_change_id = Column(String, nullable=True, index=True)
    superdocs_job_id = Column(String, nullable=True, index=True)

    # Relationships
    workflow_run = relationship("WorkflowRun", back_populates="claims")
    review = relationship("Review", back_populates="claims")

    # Indexes
    __table_args__ = (
        Index("ix_claims_workflow_run_status", "workflow_run_id", "status"),
        Index("ix_claims_review_id", "review_id"),
        Index("ix_claims_superdocs_job_id", "superdocs_job_id"),
    )
