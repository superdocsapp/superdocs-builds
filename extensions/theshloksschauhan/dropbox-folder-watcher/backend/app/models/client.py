"""Client model."""
import uuid
from sqlalchemy import Column, String, DateTime, Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base

class Client(Base):
    """Client model representing a tenant."""
    __tablename__ = 'clients'

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    dropbox_folder_root = Column(String(1024), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    folder_configs = relationship("FolderConfig", back_populates="client")
    jobs = relationship("Job", back_populates="client")
