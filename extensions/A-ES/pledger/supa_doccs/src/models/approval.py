# src/models/approval.py
"""SQLAlchemy models for approval_queue and decisions tables."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class ApprovalQueue(Base):
    """Claims/items pending human review.

    Implements optimistic concurrency control via the version column.
    Status transitions: pending → approved | rejected.

    claim_id is optional: items may be enqueued without a backing claim
    (e.g. conflicts or proposed updates from the incremental flow).
    run_id/item_type/payload carry the ApprovalService item contract.
    """

    __tablename__ = "approval_queue"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    claim_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    assigned_reviewer: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    queued_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("NOW()")
    )
    priority: Mapped[int] = mapped_column(
        nullable=False, server_default=text("3")
    )
    version: Mapped[int] = mapped_column(
        nullable=False, server_default=text("1")
    )
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    item_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'finding'")
    )
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    claim: Mapped["Claim"] = relationship(back_populates="approval_queue_entries")
    decision: Mapped[Optional["Decision"]] = relationship(
        back_populates="approval_queue_entry", uselist=False
    )


class Decision(Base):
    """Recorded human judgments on queued claims.

    The unique constraint on approval_queue_id ensures exactly one
    decision per queue entry.
    """

    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    approval_queue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_queue.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    decision_value: Mapped[str] = mapped_column(String(10), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("NOW()")
    )
    justification: Mapped[str] = mapped_column(String(2000), nullable=False)

    # Relationships
    approval_queue_entry: Mapped["ApprovalQueue"] = relationship(
        back_populates="decision"
    )
