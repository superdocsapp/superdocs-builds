import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, Integer, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.time import utc_now


class BatesAssignment(Base):
    __tablename__ = "bates_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packets.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    bates_number: Mapped[int] = mapped_column(Integer, nullable=False)
    bates_label: Mapped[str] = mapped_column(String(100), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    packet: Mapped["Packet"] = relationship("Packet", back_populates="bates_assignments")
    document: Mapped["Document"] = relationship("Document", back_populates="bates_assignments")
    page: Mapped["Page"] = relationship("Page", back_populates="bates_assignment")

    __table_args__ = (
        UniqueConstraint("packet_id", "bates_number", name="uq_bates_packet_number"),
        UniqueConstraint("packet_id", "document_id", "page_number", name="uq_bates_packet_doc_page"),
        Index("ix_bates_packet_doc", "packet_id", "document_id"),
        Index("ix_bates_number", "bates_number"),
    )

    @property
    def formatted_bates(self) -> str:
        return self.bates_label