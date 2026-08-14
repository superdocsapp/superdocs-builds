"""Database models.

TENANT ISOLATION DESIGN (why it looks like this):
- Every tenant-owned row carries a non-null `tenant_id` FK to `tenants`.
- There is NO table a tenant can reach that is not scoped by `tenant_id`.
- Authorization is done at the data layer (see repositories.py), not in each
  handler, so a forgotten `WHERE tenant_id = ?` cannot silently leak data.
- Unique constraints that must be per-tenant (idempotency keys) are composite
  on `(tenant_id, key)` so two tenants may reuse the same key independently.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_col, utcnow, uuid_pk


class JobType(str, enum.Enum):
    UPLOAD = "upload"
    EDIT = "edit"
    EXPORT = "export"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentStatus(str, enum.Enum):
    UPLOADING = "uploading"
    READY = "ready"
    FAILED = "failed"


class ChangeStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class IdempotencyStatus(str, enum.Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="tenant")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # We store only a hash of the key. The plaintext is shown once at creation
    # and never persisted, so a DB leak cannot reveal usable credentials.
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    created_at: Mapped[datetime] = created_at_col()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="api_keys")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False, length=32),
        nullable=False,
        default=DocumentStatus.UPLOADING,
    )
    # Mapping our opaque id -> SuperDocs identifiers. Kept per tenant so a
    # SuperDocs id is only ever reachable through the owning tenant's row.
    superdocs_document_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    superdocs_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[JobType] = mapped_column(
        Enum(JobType, native_enum=False, length=16), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=24),
        nullable=False,
        default=JobStatus.QUEUED,
    )
    superdocs_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Checkpoint lets a crashed worker resume without re-charging SuperDocs ops.
    checkpoint: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ops_cost: Mapped[float] = mapped_column(default=0.0, nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ProposedChange(Base):
    __tablename__ = "proposed_changes"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The parsed diff object (already double-parsed from SuperDocs' JSON string).
    diff: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[ChangeStatus] = mapped_column(
        Enum(ChangeStatus, native_enum=False, length=16),
        nullable=False,
        default=ChangeStatus.PENDING,
    )
    feedback: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Reference SuperDocs uses to identify this change when we forward decisions.
    superdocs_change_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        # Per-tenant uniqueness: the SAME key is independent across tenants, and
        # a duplicate within a tenant is rejected by the DB (the race guard).
        UniqueConstraint("tenant_id", "key", name="uq_idempotency_tenant_key"),
        Index("ix_idempotency_tenant_key", "tenant_id", "key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    # Hash of the request body: same key + different body -> 409 (not a silent
    # wrong replay).
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[IdempotencyStatus] = mapped_column(
        Enum(IdempotencyStatus, native_enum=False, length=16),
        nullable=False,
        default=IdempotencyStatus.PROCESSING,
    )
    response_status: Mapped[int | None] = mapped_column(nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = created_at_col()
