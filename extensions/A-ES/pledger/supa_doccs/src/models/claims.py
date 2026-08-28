# src/models/claims.py
"""SQLAlchemy models for claims and source_locations tables."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class Claim(Base):
    """Factual assertions extracted from document versions."""

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    extracted_text: Mapped[str] = mapped_column(String(10000), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False
    )
    extracted_at: Mapped[datetime] = mapped_column(
        server_default=text("NOW()"), nullable=False
    )
    # Document fact view: the extractor's field name and how it was
    # extracted ('structured' | 'llm' | 'llm_fallback' | 'regex_fallback').
    field_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    extraction_method: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )

    # Relationships
    source_locations: Mapped[list["SourceLocation"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    approval_queue_entries: Mapped[list["ApprovalQueue"]] = relationship(
        back_populates="claim"
    )


class SourceLocation(Base):
    """Precise positions within a document version where a claim originates."""

    __tablename__ = "source_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    page_number: Mapped[Optional[int]] = mapped_column(nullable=True)
    section_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    start_offset: Mapped[int] = mapped_column(nullable=False)
    end_offset: Mapped[int] = mapped_column(nullable=False)
    clause_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Relationships
    claim: Mapped["Claim"] = relationship(back_populates="source_locations")
