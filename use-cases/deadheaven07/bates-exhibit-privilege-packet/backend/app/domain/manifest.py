import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.time import utc_now


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.packet import Packet
    from app.domain.document import Document


class Manifest(Base):
    __tablename__ = "manifests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    packet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("packets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bates_start: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bates_end: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    validation_passed: Mapped[bool | None] = mapped_column(nullable=True)
    validation_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_packet_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_packet_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    packet: Mapped["Packet"] = relationship("Packet")  # noqa: F821
    entries: Mapped[list["ManifestEntry"]] = relationship(  # noqa: F821
        "ManifestEntry",
        back_populates="manifest",
        cascade="all, delete-orphan",
        order_by="ManifestEntry.exhibit_identifier",
    )


class ManifestEntry(Base):
    __tablename__ = "manifest_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manifest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manifests.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    exhibit_identifier: Mapped[str] = mapped_column(String(50), nullable=False)
    bates_start: Mapped[str] = mapped_column(String(100), nullable=False)
    bates_end: Mapped[str] = mapped_column(String(100), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    original_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    privilege_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    privilege_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    privilege_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    applied_redactions: Mapped[list[dict]] = mapped_column(JSON, nullable=True, default=list)
    final_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    page_hashes: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    merkle_root: Mapped[str | None] = mapped_column(String(64), nullable=True)

    manifest: Mapped["Manifest"] = relationship("Manifest", back_populates="entries")  # noqa: F821
    document: Mapped["Document"] = relationship("Document")  # noqa: F821

    __table_args__ = (
        Index("ix_manifest_entry_manifest", "manifest_id"),
        Index("ix_manifest_entry_exhibit", "exhibit_identifier"),
    )
