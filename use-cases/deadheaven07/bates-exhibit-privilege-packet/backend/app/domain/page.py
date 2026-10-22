import uuid
from sqlalchemy import String, ForeignKey, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[float | None] = mapped_column(nullable=True)
    height: Mapped[float | None] = mapped_column(nullable=True)
    rotation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_text: Mapped[bool] = mapped_column(nullable=False, default=False)
    extracted_text: Mapped[str | None] = mapped_column(String(1000000), nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="pages")
    bates_assignment: Mapped["BatesAssignment"] = relationship(
        "BatesAssignment", back_populates="page", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_pages_document_number", "document_id", "page_number", unique=True),
    )