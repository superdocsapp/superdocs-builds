"""
Domain models. Design note: SuperDocs already durably tracks every proposed
change and its decision (GET /v1/sessions/{id}/jobs). These tables are NOT a
parallel copy of that — they add exactly what SuperDocs has no way to know:
which side's position a redline reconciles toward, and whether a specific
clause is still contested ACROSS rounds (SuperDocs' history is job-scoped,
this is clause-scoped). tracker_service.py is where the two get reconciled.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Negotiation(Base):
    __tablename__ = "negotiations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    superdocs_session_id: Mapped[str] = mapped_column(String, unique=True)
    cba_document_id: Mapped[str] = mapped_column(String)
    union_attachment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    employer_attachment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rounds: Mapped[list["Round"]] = relationship(back_populates="negotiation")


class RoundStatus(StrEnum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class Round(Base):
    """One redline round == one SuperDocs chat_async job."""

    __tablename__ = "rounds"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    negotiation_id: Mapped[str] = mapped_column(String, ForeignKey("negotiations.id"))
    round_number: Mapped[int] = mapped_column()
    superdocs_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default=RoundStatus.PENDING)
    prompt_used: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    negotiation: Mapped["Negotiation"] = relationship(back_populates="rounds")


class OpenItemStatus(StrEnum):
    OPEN = "open"          # proposed, not yet decided
    APPROVED = "approved"  # decided and applied
    REJECTED = "rejected"  # decided, not applied
    REOPENED = "reopened"  # a later round proposed a change to a previously-decided clause


class OpenItem(Base):
    """
    The tracker's core row: one per clause (chunk_id) that has ever had a
    redline proposed against it, current status, reconciled against
    SuperDocs' job history rather than trusted blindly from our own writes.
    """

    __tablename__ = "open_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    negotiation_id: Mapped[str] = mapped_column(String, ForeignKey("negotiations.id"))
    chunk_id: Mapped[str] = mapped_column(String)
    clause_label: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default=OpenItemStatus.OPEN)
    raised_by: Mapped[str] = mapped_column(String, default="unknown")  # "union" | "employer" | "unknown"
    first_round_id: Mapped[str] = mapped_column(String, ForeignKey("rounds.id"))
    last_round_id: Mapped[str] = mapped_column(String, ForeignKey("rounds.id"))
    last_diff_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
