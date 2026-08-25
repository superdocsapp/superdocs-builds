"""
@file: backend/models/theme.py
@description: The Theme entity: a cluster of conversations sharing a root issue, carrying
    volume, QoQ comparison, representative quotes and evidence citations.
@flow: created by theme_node -> quotes attached by anonymize_node -> QoQ fields filled by
    compare_node -> rendered by draft_node.
@dependencies:
    - backend.models.base: declarative Base, shared enums, portable column types
    - sqlalchemy.orm: Mapped / mapped_column / relationship
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.config import settings
from backend.models.types import VectorType
from backend.models.base import (
    Base,
    JSONType,
    TrendDirection,
    UUIDType,
)

if TYPE_CHECKING:
    from backend.models.conversation import Conversation
    from backend.models.run import Run

class Theme(Base):
    """A cluster of conversations sharing a root issue."""

    __tablename__ = "themes"
    __table_args__ = (Index("ix_themes_run_volume", "run_id", "volume_count"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    volume_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    volume_share: Mapped[float] = mapped_column(Float, default=0.0)

    # Centroid of member conversation embeddings. Used to match this quarter's themes
    # against last quarter's by meaning rather than by name, so a renamed theme is
    # still recognised as the same issue.
    embedding: Mapped[list[float] | None] = mapped_column(
        VectorType(settings.embedding_dim)
    )

    prior_quarter_count: Mapped[int | None] = mapped_column(Integer)
    prior_theme_name: Mapped[str | None] = mapped_column(String(256))
    match_similarity: Mapped[float | None] = mapped_column(Float)
    growth_rate: Mapped[float | None] = mapped_column(Float)
    volume_trend: Mapped[TrendDirection] = mapped_column(
        SAEnum(TrendDirection, name="trend_direction"),
        default=TrendDirection.UNKNOWN,
        nullable=False,
    )

    representative_quotes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONType, default=list
    )
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)

    # Set when the theme's supporting evidence is too thin to state a conclusion. The
    # draft renders a caveat instead of an assertion — this is the mechanism behind
    # "never bluffs".
    confidence_note: Mapped[str | None] = mapped_column(Text)

    run: Mapped["Run"] = relationship(back_populates="themes")
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="theme"
    )

    @property
    def volume_delta(self) -> int | None:
        if self.prior_quarter_count is None:
            return None
        return self.volume_count - self.prior_quarter_count
