import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.time import utc_now


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.document import Document
    from app.domain.bates import BatesAssignment
    from app.domain.privilege import PrivilegeDecision
    from app.domain.audit import AuditEvent


class Packet(Base):
    __tablename__ = "packets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    bates_prefix: Mapped[str] = mapped_column(String(50), nullable=False, default="CASE-")
    bates_start_number: Mapped[int] = mapped_column(nullable=False, default=1)
    bates_padding: Mapped[int] = mapped_column(nullable=False, default=6)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        "Document",
        back_populates="packet",
        cascade="all, delete-orphan",
        order_by="Document.display_order",
    )
    bates_assignments: Mapped[list["BatesAssignment"]] = relationship(  # noqa: F821
        "BatesAssignment", back_populates="packet", cascade="all, delete-orphan"
    )
    privilege_decisions: Mapped[list["PrivilegeDecision"]] = relationship(  # noqa: F821
        "PrivilegeDecision", back_populates="packet", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(  # noqa: F821
        "AuditEvent", back_populates="packet", cascade="all, delete-orphan"
    )

    async def next_display_order(self, session: AsyncSession | None = None) -> int:
        if session is None:
            if not self.documents:
                return 1
            return max(d.display_order for d in self.documents) + 1

        # Use a direct query to avoid lazy loading issues
        # Import here to avoid circular imports
        from sqlalchemy import func, select

        from app.domain.document import Document

        result = await session.execute(
            select(func.max(Document.display_order)).where(Document.packet_id == self.id)
        )
        max_order = result.scalar()
        return (max_order or 0) + 1
