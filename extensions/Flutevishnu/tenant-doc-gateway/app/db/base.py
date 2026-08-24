"""Declarative base and shared column helpers.

Types are chosen to work on BOTH Postgres (production) and SQLite (tests) so the
exact same models and code paths run in CI with zero external services.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    # SQLAlchemy's Uuid type renders as native UUID on Postgres and CHAR(32) on
    # SQLite, so ids are portable across both without custom types.
    return mapped_column(primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    # Python-side default keeps timezone-aware timestamps consistent across DBs.
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
