from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, UUIDMixin, TimestampMixin


class Workspace(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workspaces"

    name = Column(String, nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    workflow_type = Column(String, nullable=True)
    status = Column(String, default="active", nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    documents = relationship("Document", back_populates="workspace", cascade="all, delete-orphan")
    workflow_runs = relationship("WorkflowRun", back_populates="workspace", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        if "owner_id" in kwargs and "owner_user_id" not in kwargs:
            kwargs["owner_user_id"] = kwargs.pop("owner_id")
        super().__init__(**kwargs)

    @property
    def owner_id(self):
        return self.owner_user_id

    @owner_id.setter
    def owner_id(self, val):
        self.owner_user_id = val
