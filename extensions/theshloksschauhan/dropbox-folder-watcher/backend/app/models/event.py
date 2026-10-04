"""Event model."""
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base

class Event(Base):
    """Event model representing state machine transitions."""
    __tablename__ = 'events'

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id = Column(Uuid, ForeignKey('jobs.id'), nullable=False, index=True)
    from_state = Column(String(50), nullable=True)
    to_state = Column(String(50), nullable=False)
    actor = Column(String(255), nullable=False)
    detail = Column(Text, nullable=True)
    occurred_at = Column(DateTime, server_default=func.now())

    job = relationship("Job", back_populates="events")
