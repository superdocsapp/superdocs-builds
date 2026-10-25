import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Submittal(Base):
    __tablename__ = "submittals"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "specification_section",
            "title",
            name="uq_submittal_identity",
        ),
    )

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    project_id: Mapped[str] = mapped_column(
        String,
        index=True,
    )

    # Human-facing register identifier.
    # Example: SR-001 / SUB-001
    number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    specification_section: Mapped[str] = mapped_column(
        String(100),
    )

    # Who is expected to provide the submittal.
    required_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Expected submission format.
    # Example: "Product data / technical sheet"
    required_form: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Evidence from the specification that caused
    # this register item to be created.
    source_evidence: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Specification revision applicable to this register item.
    # Example: "Rev 02"
    specification_revision: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # Existing review lifecycle status.
    status: Mapped[str] = mapped_column(
        String(50),
        default="PENDING",
    )

    # Register/submission tracking status.
    # This is intentionally separate from review status.
    register_status: Mapped[str] = mapped_column(
        String(50),
        default="NOT_RECEIVED",
    )

    due_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
