"""
@file: backend/models/approval.py
@description: The ApprovalItem entity: one unit a human must accept or reject at the gate.
@flow: created by human_gate_node -> decided via the approve API or the MCP tool -> read
    back by human_gate_node when the run resumes.
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
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import (
    ApprovalItemType,
    ApprovalStatus,
    Base,
    JSONType,
    UUIDType,
    utcnow,
)

if TYPE_CHECKING:
    from backend.models.run import Run

class ApprovalItem(Base):
    """One unit a human must accept or reject at the gate.

    Rejecting one item never discards the others: each row carries its own status, and
    the draft is assembled from whatever survived.
    """

    __tablename__ = "approval_items"
    __table_args__ = (Index("ix_approval_run_status", "run_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )

    item_type: Mapped[ApprovalItemType] = mapped_column(
        SAEnum(ApprovalItemType, name="approval_item_type"), nullable=False
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, name="approval_status"),
        default=ApprovalStatus.PENDING,
        nullable=False,
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Links this gate item to the SuperDocs change it will approve during upload, when
    # the item corresponds to a document edit rather than an analysis finding.
    superdocs_change_id: Mapped[str | None] = mapped_column(String(128))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    run: Mapped["Run"] = relationship(back_populates="approval_items")
