# src/models/piles.py
"""SQLAlchemy models for piles and pile_documents tables."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class Pile(Base):
    """Model mapping to the piles table.

    A pile groups related documents together (e.g., a loan application package).
    Runs are started against a pile.
    """

    __tablename__ = "piles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("NOW()")
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # Relationships
    documents: Mapped[list["PileDocument"]] = relationship(
        "PileDocument", back_populates="pile", cascade="all, delete-orphan"
    )


class PileDocument(Base):
    """Junction table: which documents belong to which pile."""

    __tablename__ = "pile_documents"

    pile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("piles.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("NOW()")
    )

    # Relationships
    pile: Mapped["Pile"] = relationship("Pile", back_populates="documents")
    document: Mapped["Document"] = relationship("Document")


# Avoid circular import — use string reference above
from src.models.documents import Document  # noqa: E402
