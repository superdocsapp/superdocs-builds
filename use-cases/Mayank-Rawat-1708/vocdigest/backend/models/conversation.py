"""
@file: backend/models/conversation.py
@description: The Conversation entity: one support conversation with its embedding,
    classification and extracted facts. source_file plus source_line form the citation
    that every theme points back to.
@flow: written by ingest_node -> classified and embedded by classify/extract -> attached to
    a Theme by theme_node.
@dependencies:
    - backend.models.base: declarative Base, shared enums, portable column types
    - sqlalchemy.orm: Mapped / mapped_column / relationship
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.config import settings
from backend.models.types import VectorType
from backend.models.base import (
    Base,
    JSONType,
    UUIDType,
)

if TYPE_CHECKING:
    from backend.models.run import Run
    from backend.models.theme import Theme

class Conversation(Base):
    """One support conversation from the input file.

    source_file + source_line are the citation: every theme's evidence refs point back
    here so a reader can find the exact line that supports a claim.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_run_theme", "run_id", "theme_id"),
        UniqueConstraint("run_id", "source_file", "source_line", name="uq_conv_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[str] = mapped_column(String(512), nullable=False)
    source_line: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    embedding: Mapped[list[float] | None] = mapped_column(
        VectorType(settings.embedding_dim)
    )

    # Set by classify_node. Conversations that are not support contacts are marked here
    # and excluded from theming rather than deleted, so the digest can honestly report
    # how many inputs it discarded and why.
    classified_type: Mapped[str | None] = mapped_column(String(64), index=True)
    is_relevant: Mapped[bool] = mapped_column(default=True, nullable=False)
    classification_reason: Mapped[str | None] = mapped_column(Text)

    extracted_facts: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    theme_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("themes.id", ondelete="SET NULL")
    )

    # Raised when the injection guard reports the content tried to address the model.
    injection_flagged: Mapped[bool] = mapped_column(default=False, nullable=False)

    run: Mapped["Run"] = relationship(back_populates="conversations")
    theme: Mapped["Theme | None"] = relationship(back_populates="conversations")

    @property
    def citation(self) -> str:
        return f"{self.source_file}:{self.source_line}"
