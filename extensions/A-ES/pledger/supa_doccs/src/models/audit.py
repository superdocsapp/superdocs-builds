# src/models/audit.py
"""SQLAlchemy model for the audit_events table."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class AuditEvent(Base):
    """Model mapping to the audit_events table.

    Immutable append-only record of all state changes in the system.
    Every mutation to any entity is captured here with previous and new state.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_timestamp: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("NOW()"),
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_state: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    new_state: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    source_ref: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
