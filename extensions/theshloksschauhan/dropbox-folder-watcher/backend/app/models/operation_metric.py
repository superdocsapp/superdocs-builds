"""OperationMetric model."""
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base

class OperationMetric(Base):
    """Model tracking performance and usage metrics."""
    __tablename__ = 'operation_metrics'

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id = Column(Uuid, ForeignKey('jobs.id'), nullable=False, index=True)
    stage = Column(String(50), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    superdocs_operations_used = Column(Integer, nullable=False, default=0)
    recorded_at = Column(DateTime, server_default=func.now())

    job = relationship("Job", back_populates="operation_metrics")
