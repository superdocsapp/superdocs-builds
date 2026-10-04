"""SuperDocsCall model."""
import uuid
from sqlalchemy import Column, String, Boolean, Text, DateTime, ForeignKey, Enum as SAEnum, Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base
from app.models.job import SuperDocsCallType

class SuperDocsCall(Base):
    """Model tracking calls to the SuperDocs API."""
    __tablename__ = 'superdocs_calls'

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id = Column(Uuid, ForeignKey('jobs.id'), nullable=False, index=True)
    call_type = Column(SAEnum(SuperDocsCallType), nullable=False)
    request_summary = Column(Text, nullable=True)
    response_summary = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)

    job = relationship("Job", back_populates="superdocs_calls")
