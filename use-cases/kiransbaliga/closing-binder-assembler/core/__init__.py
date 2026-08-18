"""Core package for M&A Closing-Binder Assembler."""

from .enums import DocumentCategory, ExecutionStatus, MatchConfidence, PriorityLevel, SignatureType
from .models import (
    AssemblyResult,
    BinderSpec,
    ChecklistItem,
    ClosingChecklist,
    DocumentMetadata,
    MatchResult,
    OutstandingItemEntry,
    OutstandingReport,
    SignatureBlock,
    TabEntry,
)

__all__ = [
    "DocumentCategory",
    "ExecutionStatus",
    "MatchConfidence",
    "PriorityLevel",
    "SignatureType",
    "SignatureBlock",
    "DocumentMetadata",
    "ChecklistItem",
    "ClosingChecklist",
    "MatchResult",
    "TabEntry",
    "BinderSpec",
    "OutstandingItemEntry",
    "OutstandingReport",
    "AssemblyResult",
]
