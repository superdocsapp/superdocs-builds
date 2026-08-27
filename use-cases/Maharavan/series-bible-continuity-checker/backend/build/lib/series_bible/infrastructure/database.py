from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from series_bible.config import get_settings

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class Series(Base, TimestampMixin):
    __tablename__ = "series"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)

class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("series_id", "content_hash", name="uq_document_series_hash"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    superdocs_session_id: Mapped[str] = mapped_column(String(256), unique=True)
    superdocs_document_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="UPLOADED")

class Chapter(Base, TimestampMixin):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("document_id", "number", name="uq_chapter_document_number"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))

class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "source_chunk_id", name="uq_document_source_chunk"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[UUID | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    source_chunk_id: Mapped[str] = mapped_column(String(256))
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraph: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

class BibleFact(Base, TimestampMixin):
    __tablename__ = "bible_facts"
    __table_args__ = (
        UniqueConstraint("series_id", "entity", "attribute", "version", name="uq_fact_version"),
        Index("ix_fact_lookup", "series_id", "entity", "attribute", "is_current"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    entity: Mapped[str] = mapped_column(String(255))
    attribute: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("bible_facts.id"), nullable=True)
    confidence: Mapped[float] = mapped_column(Float)

class Character(Base, TimestampMixin):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("series_id", "canonical_name", name="uq_character_name"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255))

class Place(Base, TimestampMixin):
    __tablename__ = "places"
    __table_args__ = (UniqueConstraint("series_id", "canonical_name", name="uq_place_name"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255))

class TimelineEvent(Base, TimestampMixin):
    __tablename__ = "timeline_events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    fact_id: Mapped[UUID] = mapped_column(ForeignKey("bible_facts.id", ondelete="CASCADE"), unique=True)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)

class WorldRule(Base, TimestampMixin):
    __tablename__ = "world_rules"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    fact_id: Mapped[UUID] = mapped_column(ForeignKey("bible_facts.id", ondelete="CASCADE"), unique=True)
    category: Mapped[str] = mapped_column(String(64))

class Evidence(Base, TimestampMixin):
    __tablename__ = "evidence"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    fact_id: Mapped[UUID | None] = mapped_column(ForeignKey("bible_facts.id", ondelete="CASCADE"), nullable=True, index=True)
    finding_id: Mapped[UUID | None] = mapped_column(ForeignKey("continuity_findings.id", ondelete="CASCADE"), nullable=True, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"))
    chapter: Mapped[str] = mapped_column(String(255))
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_id: Mapped[str] = mapped_column(String(256))
    exact_text: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="FACT")

class ContinuityFinding(Base, TimestampMixin):
    __tablename__ = "continuity_findings"
    __table_args__ = (UniqueConstraint("run_id", "fingerprint", name="uq_finding_run_fingerprint"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    existing_fact_id: Mapped[UUID | None] = mapped_column(ForeignKey("bible_facts.id"), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))
    entity: Mapped[str] = mapped_column(String(255))
    attribute: Mapped[str] = mapped_column(String(255))
    existing_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    version: Mapped[int] = mapped_column(Integer, default=1)

class ReviewDecision(Base, TimestampMixin):
    __tablename__ = "review_decisions"
    __table_args__ = (UniqueConstraint("finding_id", name="uq_review_finding"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    finding_id: Mapped[UUID] = mapped_column(ForeignKey("continuity_findings.id", ondelete="CASCADE"))
    actor: Mapped[str] = mapped_column(String(200))
    resolution: Mapped[str] = mapped_column(String(32))
    rationale: Mapped[str] = mapped_column(Text, default="")

class ProposedChange(Base, TimestampMixin):
    __tablename__ = "proposed_changes"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    finding_id: Mapped[UUID] = mapped_column(ForeignKey("continuity_findings.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"))
    instruction: Mapped[str] = mapped_column(Text)
    superdocs_job_id: Mapped[str] = mapped_column(String(256), unique=True)
    superdocs_change_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    original_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="AWAITING_APPROVAL")
    version: Mapped[int] = mapped_column(Integer, default=1)

class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True)
    current_stage: Mapped[str] = mapped_column(String(64), default="INGEST")
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    completed_stages: Mapped[list[str]] = mapped_column(JSON, default=list)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)

class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (UniqueConstraint("run_id", "stage", name="uq_workflow_run_stage"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("workflow_runs.id"), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(200))
    entity: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

async def get_session():
    async with SessionFactory() as session:
        yield session
