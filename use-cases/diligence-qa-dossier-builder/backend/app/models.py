import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, JSON, LargeBinary, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from backend.app.database import Base
from backend.app.config import settings

class Document(Base):
    """
    Model representing an uploaded document in the diligence data room.
    """
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_type = Column(String(50), nullable=False)
    hash_sha256 = Column(String(64), unique=True, nullable=False, index=True)
    storage_path = Column(String(1024), nullable=True)
    status = Column(String(50), default="pending", nullable=False)  # pending, processing, completed, failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship to chunks
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

class DocumentChunk(Base):
    """
    Model representing a text chunk from a document, along with its vector embedding.
    """
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)  # Page index (1-based), where applicable
    section = Column(String(255), nullable=True)   # Current section / heading context
    content = Column(Text, nullable=False)
    
    # pgvector embedding column, size is configuration-driven
    embedding = Column(Vector(settings.EMBEDDING_DIMENSION), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship to parent document
    document = relationship("Document", back_populates="chunks")

# PERSISTENT CHECKPOINTER MODELS

class CheckpointModel(Base):
    __tablename__ = "langgraph_checkpoints"
    
    thread_id = Column(String(255), primary_key=True)
    checkpoint_ns = Column(String(255), primary_key=True, default="")
    checkpoint_id = Column(String(255), primary_key=True)
    checkpoint_type = Column(String(50), nullable=False)
    checkpoint_bytes = Column(LargeBinary, nullable=False)
    metadata_type = Column(String(50), nullable=False)
    metadata_bytes = Column(LargeBinary, nullable=False)
    parent_checkpoint_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

class CheckpointWriteModel(Base):
    __tablename__ = "langgraph_checkpoint_writes"
    
    thread_id = Column(String(255), primary_key=True)
    checkpoint_ns = Column(String(255), primary_key=True, default="")
    checkpoint_id = Column(String(255), primary_key=True)
    task_id = Column(String(255), primary_key=True)
    idx = Column(Integer, primary_key=True)
    channel = Column(String(255), nullable=False)
    write_type = Column(String(50), nullable=False)
    write_bytes = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

class CheckpointBlobModel(Base):
    __tablename__ = "langgraph_checkpoint_blobs"
    
    thread_id = Column(String(255), primary_key=True)
    checkpoint_ns = Column(String(255), primary_key=True, default="")
    channel = Column(String(255), primary_key=True)
    version = Column(String(255), primary_key=True)
    blob_type = Column(String(50), nullable=False)
    blob_bytes = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

# DOSSIER MODELS

class Dossier(Base):
    """
    Model representing a batch diligence review dossier consisting of multiple findings.
    """
    __tablename__ = "dossiers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # pending, running, completed, failed, review_required
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    findings = relationship("DossierFinding", back_populates="dossier", cascade="all, delete-orphan")

class DossierFinding(Base):
    """
    Model representing an individual diligence question finding within a dossier.
    """
    __tablename__ = "dossier_findings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dossier_id = Column(UUID(as_uuid=True), ForeignKey("dossiers.id", ondelete="CASCADE"), nullable=False)
    question = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # pending, running, answered, insufficient_evidence, conflict, failed
    review_status = Column(String(50), nullable=False, default="not_required")  # not_required, pending, approved, rejected, edited
    answer = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    reasoning_summary = Column(Text, nullable=True)
    citations = Column(JSON, nullable=True)
    supporting_evidence = Column(JSON, nullable=True)
    contradicting_evidence = Column(JSON, nullable=True)
    workflow_thread_id = Column(String(255), nullable=False, unique=True)
    review_reason = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    dossier = relationship("Dossier", back_populates="findings")
    history = relationship("FindingExecutionHistory", back_populates="finding", cascade="all, delete-orphan")

class FindingExecutionHistory(Base):
    """
    Model representing historical runs/re-runs of a finding to preserve a clean audit trail.
    """
    __tablename__ = "finding_execution_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finding_id = Column(UUID(as_uuid=True), ForeignKey("dossier_findings.id", ondelete="CASCADE"), nullable=False)
    workflow_thread_id = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)
    answer = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    reasoning_summary = Column(Text, nullable=True)
    citations = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    
    finding = relationship("DossierFinding", back_populates="history")


class WorkflowExecutionMetric(Base):
    """
    Model representing execution duration, token counts, and cost metrics
    per node/stage in a diligence workflow run.
    """
    __tablename__ = "workflow_execution_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dossier_id = Column(UUID(as_uuid=True), ForeignKey("dossiers.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_id = Column(UUID(as_uuid=True), ForeignKey("dossier_findings.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(255), nullable=False)  # thread/run ID
    stage_name = Column(String(255), nullable=False)  # node name
    status = Column(String(50), nullable=False)  # success, failed
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    model_name = Column(String(255), nullable=True)
    provider_name = Column(String(255), nullable=True)
    estimated_cost = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
