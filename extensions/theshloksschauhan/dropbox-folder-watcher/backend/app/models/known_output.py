"""KnownOutput model."""
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base

class KnownOutput(Base):
    """Model tracking known generated outputs."""
    __tablename__ = 'known_outputs'

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id = Column(Uuid, ForeignKey('jobs.id'), nullable=False, index=True)
    output_path = Column(String(1024), nullable=False, index=True)
    output_rev = Column(String(128), nullable=True)
    output_content_hash = Column(String(128), nullable=True)
    written_at = Column(DateTime, server_default=func.now())

    job = relationship("Job", back_populates="known_outputs")
