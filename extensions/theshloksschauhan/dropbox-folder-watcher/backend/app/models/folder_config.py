"""FolderConfig model."""
import uuid
from sqlalchemy import Column, String, Boolean, Integer, Text, DateTime, ForeignKey, JSON, Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base

class FolderConfig(Base):
    """Folder configuration model for processing Dropbox folders."""
    __tablename__ = 'folder_configs'

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id = Column(Uuid, ForeignKey('clients.id'), nullable=False, index=True)
    dropbox_folder_path = Column(String(1024), unique=True, nullable=False)
    treatment = Column(String(255), nullable=False)
    template_id = Column(String(255), nullable=True)
    instruction_text = Column(Text, nullable=True)
    output_naming_pattern = Column(String(512), nullable=False, default='{basename}.superdocs.{treatment}{ext}')
    allowed_extensions = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    preview_mode = Column(Boolean, nullable=False, default=False)
    debounce_seconds = Column(Integer, nullable=False, default=30)
    operation_budget_per_hour = Column(Integer, nullable=False, default=20)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    client = relationship("Client", back_populates="folder_configs")
