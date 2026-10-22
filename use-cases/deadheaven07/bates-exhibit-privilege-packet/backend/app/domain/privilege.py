import enum
import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Enum, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.time import utc_now


class PrivilegeStatus(str, enum.Enum):
    PENDING = "pending"
    PRIVILEGED = "privileged"
    NOT_PRIVILEGED = "not_privileged"


class PrivilegeCategory(str, enum.Enum):
    ATTORNEY_CLIENT = "attorney_client"
    WORK_PRODUCT = "work_product"
    OTHER = "other"


class PrivilegeDecision(Base):
    __tablename__ = "privilege_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packets.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[PrivilegeStatus] = mapped_column(
        Enum(PrivilegeStatus), nullable=False, default=PrivilegeStatus.PENDING
    )
    category: Mapped[PrivilegeCategory | None] = mapped_column(
        Enum(PrivilegeCategory), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    bates_start: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bates_end: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    packet: Mapped["Packet"] = relationship("Packet", back_populates="privilege_decisions")
    document: Mapped["Document"] = relationship("Document", back_populates="privilege_decisions")

    __table_args__ = (
        Index("ix_privilege_packet_doc", "packet_id", "document_id", unique=True),
        Index("ix_privilege_status", "status"),
    )