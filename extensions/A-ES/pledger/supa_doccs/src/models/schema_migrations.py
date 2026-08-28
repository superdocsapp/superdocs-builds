# src/models/schema_migrations.py
"""SQLAlchemy model for the schema_migrations table."""

from datetime import datetime

from sqlalchemy import Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class SchemaMigration(Base):
    """Tracks applied database migrations."""

    __tablename__ = "schema_migrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
