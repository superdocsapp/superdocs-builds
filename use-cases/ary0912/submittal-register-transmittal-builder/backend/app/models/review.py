import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    finding_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("findings.id"),
        index=True,
    )

    reviewer: Mapped[str] = mapped_column(
        String(255)
    )

    decision: Mapped[str] = mapped_column(
        String(50)
    )

    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )