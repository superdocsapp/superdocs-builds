import uuid
from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Text, JSON, Integer, func, Uuid
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database import Base
from app.config import settings

class Run(Base):
    __tablename__ = "runs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="pending")  # pending, running, paused, completed, failed
    current_stage = Column(String(100), nullable=True)
    graph_state = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    stages = relationship("RunStage", back_populates="run", cascade="all, delete-orphan")
    deliverables = relationship("Deliverable", back_populates="run", cascade="all, delete-orphan")
    conflicts = relationship("Conflict", back_populates="run", cascade="all, delete-orphan")
    compliance_findings = relationship("ComplianceFinding", back_populates="run", cascade="all, delete-orphan")


class RunStage(Base):
    __tablename__ = "run_stages"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id = Column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # pending, running, completed, skipped, failed
    latency_seconds = Column(Float, nullable=True, default=0.0)
    token_cost_usd = Column(Float, nullable=True, default=0.0)
    completed_at = Column(DateTime, nullable=True)

    run = relationship("Run", back_populates="stages")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id = Column(String(255), nullable=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # contract, amendment, invoice
    file_hash = Column(String(64), nullable=False)
    file_path = Column(String(512), nullable=False)
    uploaded_at = Column(DateTime, server_default=func.now())

    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    conflicts = relationship("Conflict", back_populates="source_doc", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id = Column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text_content = Column(Text, nullable=False)
    # Gemini text-embedding-004 outputs 768-dimensional embeddings. Use JSON if pgvector is not available.
    if settings.USE_PGVECTOR:
        embedding = Column(Vector(768), nullable=True)
    else:
        embedding = Column(JSON, nullable=True)

    document = relationship("Document", back_populates="chunks")


class Deliverable(Base):
    __tablename__ = "deliverables"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id = Column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    content_markdown = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)  # mapping of claims to source document references
    is_committed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())

    run = relationship("Run", back_populates="deliverables")


class Conflict(Base):
    __tablename__ = "conflicts"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id = Column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    source_doc_id = Column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    conflict_description = Column(Text, nullable=False)
    expected_value = Column(String(255), nullable=True)
    actual_value = Column(String(255), nullable=True)
    human_decision = Column(String(50), nullable=False, default="pending")  # pending, approved (override/accept new), rejected (keep old)
    resolved_at = Column(DateTime, nullable=True)

    run = relationship("Run", back_populates="conflicts")
    source_doc = relationship("Document", back_populates="conflicts")


class ComplianceFinding(Base):
    __tablename__ = "compliance_findings"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id = Column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    rule_name = Column(String(100), nullable=False)
    rule_description = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="flagged")  # flagged, passed
    details = Column(Text, nullable=True)
    citation_reference = Column(String(255), nullable=True)
    human_decision = Column(String(50), nullable=False, default="pending")  # pending, approved (escalated/exception), rejected (must correct)
    resolved_at = Column(DateTime, nullable=True)

    run = relationship("Run", back_populates="compliance_findings")


class SubstitutionRun(Base):
    __tablename__ = "substitution_runs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id = Column(String(255), nullable=False)
    job_id = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="uploading")  # uploading, analyzing, awaiting_approval, approved, rejected, failed
    spec_doc_id = Column(String(255), nullable=True)
    schedule_doc_id = Column(String(255), nullable=True)
    cutsheet_filename = Column(String(255), nullable=True)
    spec_filename = Column(String(255), nullable=True)
    schedule_filename = Column(String(255), nullable=True)
    comparison_report = Column(Text, nullable=True)
    response_letter = Column(Text, nullable=True)
    pending_changes = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

