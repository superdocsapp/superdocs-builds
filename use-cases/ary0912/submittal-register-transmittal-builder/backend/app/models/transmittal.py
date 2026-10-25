import uuid

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.db.session import Base


class Transmittal(Base):

    __tablename__ = "transmittals"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(
            uuid.uuid4()
        ),
    )

    project_id: Mapped[str] = mapped_column(
        String,
        index=True,
    )

    submittal_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("submittals.id"),
        index=True,
    )

    number: Mapped[str] = mapped_column(
        String(50)
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="DRAFT",
    )

    superdocs_session_id: Mapped[
        str | None
    ] = mapped_column(
        String,
        nullable=True,
    )

    superdocs_job_id: Mapped[
        str | None
    ] = mapped_column(
        String,
        nullable=True,
    )

    export_url: Mapped[
        str | None
    ] = mapped_column(
        String,
        nullable=True,
    )

    created_at: Mapped[
        datetime
    ] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
