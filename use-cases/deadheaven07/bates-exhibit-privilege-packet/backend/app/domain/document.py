import enum
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Integer, Enum, Index, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.time import utc_now


class DocumentType(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    SCANNED_PDF = "scanned_pdf"
    IMAGE = "image"
    UNKNOWN = "unknown"


class ProcessingStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    OCR = "ocr"
    AI_ANALYSIS = "ai_analysis"
    WAITING_REVIEW = "waiting_review"
    APPROVED = "approved"
    BATES_ASSIGNED = "bates_assigned"
    ASSEMBLING = "assembling"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packets.id", ondelete="CASCADE"), nullable=False
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType), nullable=False, default=DocumentType.UNKNOWN
    )
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus), nullable=False, default=ProcessingStatus.QUEUED
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_completed_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    original_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    superdocs_session_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    superdocs_document_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_searchable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    packet: Mapped["Packet"] = relationship("Packet", back_populates="documents")
    pages: Mapped[list["Page"]] = relationship(
        "Page", back_populates="document", cascade="all, delete-orphan", order_by="Page.page_number"
    )
    bates_assignments: Mapped[list["BatesAssignment"]] = relationship(
        "BatesAssignment", back_populates="document", cascade="all, delete-orphan"
    )
    privilege_decisions: Mapped[list["PrivilegeDecision"]] = relationship(
        "PrivilegeDecision", back_populates="document", cascade="all, delete-orphan"
    )
    redaction_candidates: Mapped[list["RedactionCandidate"]] = relationship(
        "RedactionCandidate", back_populates="document", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        "AuditEvent", back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_packet_order", "packet_id", "display_order"),
        Index("ix_documents_sha256", "sha256"),
        Index("ix_documents_status", "processing_status"),
    )