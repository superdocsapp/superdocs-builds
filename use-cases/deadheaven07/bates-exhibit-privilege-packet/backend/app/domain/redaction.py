import enum
import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Enum, Text, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.time import utc_now


class RedactionStatus(str, enum.Enum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    VERIFIED = "verified"
    FAILED = "failed"


class RedactionCategory(str, enum.Enum):
    NAME = "name"
    ACCOUNT_NUMBER = "account_number"
    MEDICAL_TERM = "medical_term"
    SSN = "ssn"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    OTHER = "other"


class RedactionCandidate(Base):
    __tablename__ = "redaction_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[RedactionCategory] = mapped_column(Enum(RedactionCategory), nullable=False)
    matched_text: Mapped[str] = mapped_column(String(500), nullable=False)
    context_before: Mapped[str | None] = mapped_column(String(200), nullable=True)
    context_after: Mapped[str | None] = mapped_column(String(200), nullable=True)
    x0: Mapped[float | None] = mapped_column(nullable=True)
    y0: Mapped[float | None] = mapped_column(nullable=True)
    x1: Mapped[float | None] = mapped_column(nullable=True)
    y1: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[RedactionStatus] = mapped_column(
        Enum(RedactionStatus), nullable=False, default=RedactionStatus.PROPOSED
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    proposed_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")

    document: Mapped["Document"] = relationship("Document", back_populates="redaction_candidates")
    approval: Mapped["RedactionApproval"] = relationship(
        "RedactionApproval", back_populates="candidate", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_redaction_doc_page", "document_id", "page_number"),
        Index("ix_redaction_status", "status"),
    )


class RedactionApproval(Base):
    __tablename__ = "redaction_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("redaction_candidates.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[RedactionStatus] = mapped_column(
        Enum(RedactionStatus), nullable=False
    )
    approver: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_passed: Mapped[bool | None] = mapped_column(nullable=True)
    verification_details: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidate: Mapped["RedactionCandidate"] = relationship("RedactionCandidate", back_populates="approval")

    __table_args__ = (
        Index("ix_redaction_approval_status", "status"),
    )