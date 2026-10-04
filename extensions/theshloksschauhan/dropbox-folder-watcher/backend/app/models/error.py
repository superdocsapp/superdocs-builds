"""Error model."""
import uuid
from sqlalchemy import Column, String, Boolean, Text, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base

class Error(Base):
    """Model for tracking processing errors."""
    __tablename__ = 'errors'

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id = Column(Uuid, ForeignKey('jobs.id'), nullable=False, index=True)
    stage = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    retryable = Column(Boolean, nullable=False, default=True)
    occurred_at = Column(DateTime, server_default=func.now())

    job = relationship("Job", back_populates="errors")
