# src/models/base.py
"""Base classes and common imports for SQLAlchemy models."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""

    pass


class TimestampMixin:
    """Mixin providing a created_at timestamp column with server-side default."""

    created_at: Mapped[datetime] = mapped_column(server_default=text("NOW()"))
