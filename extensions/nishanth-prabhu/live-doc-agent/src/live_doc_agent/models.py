"""Data models and custom exceptions for Live Doc Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LiveDocAgentError(Exception):
    """Base exception for live-doc-agent errors."""


class ConflictError(LiveDocAgentError):
    """Raised when document version mismatch occurs (optimistic locking failure)."""


class PatchAmbiguityError(LiveDocAgentError):
    """Raised when a patch target snippet matches zero or multiple locations."""


class SectionNotFoundError(LiveDocAgentError):
    """Raised when a targeted section does not exist in the document."""


class ProposalValidationError(LiveDocAgentError):
    """Raised when an AI proposed change fails pre-approval validation."""


class SuperDocsAPIError(LiveDocAgentError):
    """Raised when an error occurs during SuperDocs API interaction."""


class PromptInjectionDetected(LiveDocAgentError):
    """Raised when malicious prompt injection or instruction hijacking is detected."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    """Status of an agent execution run."""

    NOOP = "noop"
    APPLIED = "applied"
    REJECTED = "rejected"
    VALIDATION_FAILED = "validation_failed"
    CONFLICT = "conflict"
    ERROR = "error"


@dataclass
class WikiSection:
    """A section of a markdown document delimited by headers or top-level content."""

    section_id: str
    title: str
    content: str
    raw_text: str
    level: int = 2
    start_line: int = 0
    end_line: int = 0


@dataclass
class WikiDocument:
    """Representation of a wiki document snapshot."""

    doc_id: str
    title: str
    content: str
    content_version: str = "1"
    sections: List[WikiSection] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProposedChange:
    """A surgical change proposed by the AI/SuperDocs."""

    change_id: str
    target_section: str
    old_snippet: str
    new_snippet: str
    explanation: str = ""
    confidence: float = 1.0


@dataclass
class ChangeDecision:
    """Human review decision for a single proposed change."""

    change_id: str
    approved: bool
    user_override_text: Optional[str] = None
    rejection_reason: Optional[str] = None


@dataclass
class Patch:
    """A validated, executable surgical patch to be applied to a document."""

    patch_id: str
    target_section: str
    original_snippet: str
    replacement_snippet: str
    expected_version: str


@dataclass
class RunResult:
    """Final outcome of an agent execution run."""

    status: RunStatus
    decision_summary: str = ""
    proposed_changes: List[ProposedChange] = field(default_factory=list)
    decisions: List[ChangeDecision] = field(default_factory=list)
    applied_patches: List[Patch] = field(default_factory=list)
    before_document: Optional[WikiDocument] = None
    after_document: Optional[WikiDocument] = None
    error_message: Optional[str] = None
