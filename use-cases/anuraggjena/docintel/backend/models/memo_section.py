from sqlalchemy import Column, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, TimestampMixin, UUIDMixin


class MemoSection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "memo_sections"
    __table_args__ = (
        Index("ix_memo_sections_run_order", "workflow_run_id", "section_order"),
        Index(
            "uq_memo_sections_run_type",
            "workflow_run_id",
            "section_type",
            unique=True,
        ),
    )

    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False)
    section_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    section_order = Column(Integer, nullable=False)
    content = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="pending")
    source_attribution = Column(JSON, nullable=True)
    analyst_reasoning = Column(Text, nullable=True)
    evidence_refs = Column(JSON, nullable=True)
    confidence = Column(String, nullable=True)
    baseline_section_id = Column(UUID(as_uuid=True), ForeignKey("memo_sections.id"), nullable=True)
    structured_data = Column(JSON, nullable=True)

    workflow_run = relationship("WorkflowRun", back_populates="memo_sections")
    baseline_section = relationship("MemoSection", remote_side="MemoSection.id")
