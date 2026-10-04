"""DropboxEvent model."""
import uuid
from sqlalchemy import Column, String, BigInteger, DateTime, ForeignKey, Uuid
from sqlalchemy.sql import func

from app.models.base import Base

class DropboxEvent(Base):
    """Dropbox event model for append-only log."""
    __tablename__ = 'dropbox_events'

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    dropbox_path = Column(String(1024), nullable=False, index=True)
    content_hash = Column(String(128), nullable=True)
    rev = Column(String(128), nullable=True)
    size = Column(BigInteger, nullable=True)
    client_modified = Column(DateTime, nullable=True)
    observed_at = Column(DateTime, server_default=func.now())
    resolved_job_id = Column(Uuid, ForeignKey('jobs.id'), nullable=True)
