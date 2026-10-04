"""Job model."""
import uuid
import enum
from sqlalchemy import Column, String, Boolean, Integer, Text, DateTime, ForeignKey, UniqueConstraint, Enum as SAEnum, Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base

class JobStatus(enum.Enum):
    """Enum for job states."""
    DISCOVERED = "DISCOVERED"
    STABILIZING = "STABILIZING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    REVIEW_PENDING = "REVIEW_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPORTING = "EXPORTING"
    WRITING_BACK = "WRITING_BACK"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class SuperDocsCallType(enum.Enum):
    """Enum for SuperDocs call types."""
    UPLOAD = "UPLOAD"
    CHAT = "CHAT"
    APPROVE = "APPROVE"
    EXPORT = "EXPORT"

class Job(Base):
    """Job model representing a processing task."""
    __tablename__ = 'jobs'

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id = Column(Uuid, ForeignKey('clients.id'), nullable=False, index=True)
    folder_config_id = Column(Uuid, ForeignKey('folder_configs.id'), nullable=False)
    source_path = Column(String(1024), nullable=False)
    source_rev = Column(String(128), nullable=False)
    source_content_hash = Column(String(128), nullable=True)
    status = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.DISCOVERED, index=True)
    superdocs_doc_id = Column(String(255), nullable=True)
    proposed_changes_json = Column(Text, nullable=True)
    preview = Column(Boolean, nullable=False, default=False)
    locked_by = Column(String(255), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('client_id', 'source_rev', name='uq_job_client_rev'),
    )

    client = relationship("Client", back_populates="jobs")
    folder_config = relationship("FolderConfig")
    superdocs_calls = relationship("SuperDocsCall", back_populates="job")
    known_outputs = relationship("KnownOutput", back_populates="job")
    events = relationship("Event", back_populates="job")
    errors = relationship("Error", back_populates="job")
    operation_metrics = relationship("OperationMetric", back_populates="job")
