from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import UUID
import uuid

from backend.database import Base


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class UUIDMixin:
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
