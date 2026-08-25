"""
@file: backend/models/base.py
@description: Declarative base, shared enums, portable column types and the utcnow
    helper. Split out so run/conversation/theme/approval can each import from one place
    without importing each other — their relationships are mutual, so a direct import
    between entity modules would be a cycle.
@flow: Base and enums declared here -> imported by each entity module -> re-exported
    by models/__init__.py so every existing import path keeps working.
@dependencies:
    - sqlalchemy: async ORM, JSONB columns, enum types
    - pgvector.sqlalchemy.Vector: embedding column for semantic theme matching
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Uuid as SA_UUID,
)
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID

# JSONB on Postgres, plain JSON elsewhere, so the same models load under SQLite in tests.
JSONType = JSON().with_variant(JSONB(), "postgresql")
# Native UUID on Postgres; SQLAlchemy renders CHAR(32) on SQLite automatically.
UUIDType = PGUUID(as_uuid=True).with_variant(SA_UUID(as_uuid=True), "sqlite")
from sqlalchemy.orm import DeclarativeBase



def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RunStatus(str, enum.Enum):
    """Lifecycle of a digest run.

    The stage-named states double as the checkpoint key: a resumed run reads its status
    to know which node to re-enter. AWAITING_APPROVAL and PAUSED are both resumable but
    mean different things — the first waits on a human, the second on an operator
    (usually after a Groq outage).
    """

    PENDING = "PENDING"
    INGESTING = "INGESTING"
    CLASSIFYING = "CLASSIFYING"
    EXTRACTING = "EXTRACTING"
    THEMING = "THEMING"
    ANONYMIZING = "ANONYMIZING"
    COMPARING = "COMPARING"
    DRAFTING = "DRAFTING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    UPLOADING = "UPLOADING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    # Requested by an operator. Distinct from FAILED (nothing went wrong) and from
    # PAUSED (a paused run is expected to resume; a cancelled one is not).
    CANCELLED = "CANCELLED"


class ApprovalItemType(str, enum.Enum):
    THEME = "THEME"
    QUOTE = "QUOTE"
    FINDING = "FINDING"
    UPDATE = "UPDATE"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TrendDirection(str, enum.Enum):
    """How a theme moved against the prior quarter.

    NEW and RESOLVED are asymmetric on purpose: NEW means present now and absent before,
    RESOLVED means present before and absent now. UNKNOWN is used when no prior digest
    was supplied at all, so the digest can say "no comparison available" rather than
    implying every theme is new.
    """

    GREW = "GREW"
    SHRANK = "SHRANK"
    STABLE = "STABLE"
    NEW = "NEW"
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"