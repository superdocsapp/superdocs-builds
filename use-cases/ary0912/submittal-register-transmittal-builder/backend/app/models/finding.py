import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    submittal_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("submittals.id"),
        index=True,
    )

    attribute: Mapped[str] = mapped_column(
        String(255)
    )

    requirement: Mapped[str] = mapped_column(
        Text
    )

    submitted_value: Mapped[str] = mapped_column(
        Text
    )

    result: Mapped[str] = mapped_column(
        String(50)
    )

    specification_evidence: Mapped[str] = mapped_column(
        Text
    )

    submission_evidence: Mapped[str] = mapped_column(
        Text
    )

    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # AI lifecycle
    status: Mapped[str] = mapped_column(
        String(50),
        default="PENDING_REVIEW",
    )

    # Human decision
    reviewer: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    reviewer_comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )