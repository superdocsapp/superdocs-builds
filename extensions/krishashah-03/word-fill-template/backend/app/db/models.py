import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, server_default="HR")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    schema_json: Mapped[dict] = mapped_column("schema", JSONB, nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    conditions: Mapped[list["TemplateCondition"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class TemplateCondition(Base):
    __tablename__ = "template_conditions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    condition_key: Mapped[str] = mapped_column(String(255), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), nullable=False, server_default="=")
    expected_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False, server_default="include")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    template: Mapped["Template"] = relationship(back_populates="conditions")


class Record(Base):
    __tablename__ = "records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    normalized_data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    file_size: Mapped[int | None] = mapped_column(nullable=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DocumentRun(Base):
    __tablename__ = "document_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("templates.id", ondelete="RESTRICT"), nullable=False
    )
    record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("records.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft")
    output_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    gaps: Mapped[list["Gap"]] = relationship(back_populates="document_run", cascade="all, delete-orphan")


class Gap(Base):
    __tablename__ = "gaps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_runs.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    resolved_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    document_run: Mapped["DocumentRun"] = relationship(back_populates="gaps")
