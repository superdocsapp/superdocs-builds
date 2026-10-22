import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.time import utc_now


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.packet import Packet
    from app.domain.document import Document


class AuditEventType(enum.StrEnum):
    UPLOAD = "upload"
    PACKET_CREATED = "packet_created"
    PACKET_UPDATED = "packet_updated"
    PACKET_DELETED = "packet_deleted"
    DOCUMENT_DELETED = "document_deleted"
    OCR_COMPLETED = "ocr_completed"
    AI_ANALYSIS_STARTED = "ai_analysis_started"
    AI_ANALYSIS_COMPLETED = "ai_analysis_completed"
    AI_ANALYSIS_FAILED = "ai_analysis_failed"
    CHANGE_PROPOSED = "change_proposed"
    CHANGE_APPROVED = "change_approved"
    CHANGE_REJECTED = "change_rejected"
    PRIVILEGE_MARKED = "privilege_marked"
    REDACTION_PROPOSED = "redaction_proposed"
    REDACTION_APPROVED = "redaction_approved"
    REDACTION_REJECTED = "redaction_rejected"
    REDACTION_APPLIED = "redaction_applied"
    REDACTION_FAILED = "redaction_failed"
    REDACTION_VERIFIED = "redaction_verified"
    BATES_ASSIGNED = "bates_assigned"
    PACKET_BUILT = "packet_built"
    PACKET_VALIDATED = "packet_validated"
    PACKET_EXPORTED = "packet_exported"
    PROCESSING_STARTED = "processing_started"
    PROCESSING_COMPLETED = "processing_completed"
    PROCESSING_FAILED = "processing_failed"
    PROCESSING_RETRIED = "processing_retried"
    DOCUMENT_REORDERED = "document_reordered"
    EXPORT_STARTED = "export_started"
    EXPORT_COMPLETED = "export_completed"
    EXPORT_FAILED = "export_failed"


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    packet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packets.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[AuditEventType] = mapped_column(Enum(AuditEventType), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    packet: Mapped["Packet"] = relationship("Packet", back_populates="audit_events")  # noqa: F821
    document: Mapped["Document"] = relationship("Document", back_populates="audit_events")  # noqa: F821

    __table_args__ = (
        Index("ix_audit_packet_time", "packet_id", "timestamp"),
        Index("ix_audit_document_time", "document_id", "timestamp"),
        Index("ix_audit_type_time", "event_type", "timestamp"),
    )
