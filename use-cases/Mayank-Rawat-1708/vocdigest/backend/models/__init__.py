"""
@file: backend/models/__init__.py
@description: Aggregates the model package. Each entity lives in its own module; this
    file imports them in dependency order so SQLAlchemy has every class registered
    before any relationship is resolved, and re-exports the full set so `from
    backend.models import Run, Theme, ...` keeps working everywhere it is already used.
@flow: base (Base, enums, column types) -> run -> theme -> conversation -> approval ->
    __all__ re-export. Order matters: Conversation has a foreign key to Theme, so Theme
    must be registered first.
@dependencies:
    - backend.models.base: declarative base and shared types
    - the four entity modules
"""

from __future__ import annotations

from backend.models.base import (
    ApprovalItemType,
    ApprovalStatus,
    Base,
    JSONType,
    RunStatus,
    TrendDirection,
    UUIDType,
    utcnow,
)
from backend.models.types import VectorType

# Import order is deliberate. Theme precedes Conversation because Conversation carries
# a ForeignKey to themes.id; registering it first avoids a resolution warning on some
# SQLAlchemy versions.
from backend.models.run import Run
from backend.models.theme import Theme
from backend.models.conversation import Conversation
from backend.models.approval import ApprovalItem

__all__ = [
    "Base",
    "JSONType",
    "UUIDType",
    "VectorType",
    "utcnow",
    "Run",
    "RunStatus",
    "Conversation",
    "Theme",
    "TrendDirection",
    "ApprovalItem",
    "ApprovalItemType",
    "ApprovalStatus",
]
