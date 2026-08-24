"""Core data model for the back-translation drift check pipeline.

Everything downstream (signals, severity, pipeline, report) is built on these
types. Models are intentionally plain ``dataclasses`` rather than a validation
framework: the project has no runtime dependencies, and validation happens at
the boundaries (parsing, provider responses) rather than in the model layer.

Frozen dataclasses are used for anything that represents an immutable fact
about the source or a point-in-time snapshot (``Section``, ``Document``,
``VerificationResult``). Mutable dataclasses are used for records that are
built up incrementally or whose review state changes over time
(``DriftFinding``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Literal


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with second precision."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"  # stylistic variation / pass, not a drift

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class DriftCategory(str, Enum):
    NEGATION_REVERSAL = "negation_reversal"
    MODAL_OBLIGATION_CHANGE = "modal_obligation_change"
    NUMERIC_CHANGE = "numeric_change"
    DATE_CHANGE = "date_change"
    PERCENTAGE_CHANGE = "percentage_change"
    UNIT_CHANGE = "unit_change"
    QUALIFIER_CHANGE = "qualifier_change"
    SCOPE_CHANGE = "scope_change"
    NAMED_ENTITY_CHANGE = "named_entity_change"
    TERMINOLOGY_CHANGE = "terminology_change"
    CONDITION_CHANGE = "condition_change"
    SEMANTIC_DRIFT_OTHER = "semantic_drift_other"
    STYLISTIC_VARIATION = "stylistic_variation"  # info / pass marker, not a real drift
    ALIGNMENT_UNCERTAIN = "alignment_uncertain"


# Categories for which this codebase implements an independent, regex/rule
# based detector. Used by severity.py to decide whether a finding is
# corroborated by a deterministic signal versus resting solely on the
# semantic-assessment layer. See DECISIONS.md #4.
DETERMINISTIC_CATEGORIES: frozenset[DriftCategory] = frozenset(
    {
        DriftCategory.NEGATION_REVERSAL,
        DriftCategory.MODAL_OBLIGATION_CHANGE,
        DriftCategory.NUMERIC_CHANGE,
        DriftCategory.DATE_CHANGE,
        DriftCategory.PERCENTAGE_CHANGE,
        DriftCategory.UNIT_CHANGE,
        DriftCategory.QUALIFIER_CHANGE,
        DriftCategory.NAMED_ENTITY_CHANGE,
    }
)


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "pending_review"  # deterministic-backed finding awaiting a human decision
    REVIEW_REQUIRED = "review_required"  # semantic-only finding, or uncertain alignment: extra scrutiny
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


@dataclass(frozen=True, slots=True)
class Section:
    """A single addressable unit of a parsed document."""

    id: str
    index: int  # 1-based, stable ordinal position — authoritative key for fixtures/lookups
    heading: str
    text: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class Document:
    """A parsed document. Immutable once constructed."""

    id: str
    language: str
    title: str
    sections: tuple[Section, ...]
    raw_text: str
    source_hash: str
    protected_terms: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SectionPair:
    source_section_id: str
    target_section_id: str
    alignment_confidence: float
    review_required: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class UsageInfo:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class SemanticAssessment:
    """The AI-assisted judgment of whether a back-translation preserves source meaning.

    This is produced *alongside* the back-translation in a single provider
    call (see providers/base.py) rather than as a second round trip, per the
    cost-discipline requirement — back-translation is unavoidable per section,
    so the semantic read is attached to that same call instead of issued
    separately.
    """

    has_drift: bool
    category: DriftCategory | None
    rationale: str
    confidence: float  # 0..1
    severity_hint: Severity | None = None  # required (non-None) whenever has_drift is True


@dataclass(frozen=True, slots=True)
class BackTranslationResult:
    target_section_id: str
    text: str
    provider: str
    model: str
    latency_ms: float
    semantic_assessment: SemanticAssessment | None
    usage: UsageInfo | None = None
    retries: int = 0


@dataclass(frozen=True, slots=True)
class Evidence:
    description: str
    source_excerpt: str
    target_excerpt: str
    back_translation_excerpt: str
    signal: str  # short machine-readable tag, e.g. "modal:MUST->SHOULD" or "numeric:30->60"


@dataclass(frozen=True, slots=True)
class ProposedCorrection:
    correction_target: Literal["translation"]
    suggested_text: str | None  # literal replacement text, only when deterministically safe
    instruction: str  # natural-language correction instruction for the human reviewer
    auto_generated_by: Literal["deterministic", "ai_assisted"]


@dataclass(slots=True)
class DriftFinding:
    id: str
    run_id: str
    source_document_id: str
    source_section_id: str
    target_section_id: str
    section_index: int
    category: DriftCategory
    severity: Severity
    source_text: str
    target_text: str
    back_translation: str
    difference: str
    evidence: list[Evidence]
    confidence: float
    proposed_correction: ProposedCorrection | None
    review_status: ReviewStatus
    verified_deterministically: bool
    semantic_corroborated: bool = False
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def is_pass(self) -> bool:
        return self.category == DriftCategory.STYLISTIC_VARIATION or self.severity == Severity.INFO


@dataclass(slots=True)
class ReviewDecision:
    finding_id: str
    decision: Literal["approved", "rejected", "edited"]
    reviewer: str
    decided_at: str
    edited_text: str | None = None
    note: str | None = None


@dataclass(slots=True)
class AuditEvent:
    run_id: str
    event: str
    timestamp: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    ok: bool
    checked_at: str
    expected_hash: str
    actual_hash: str
    message: str


@dataclass(slots=True)
class RunMetrics:
    run_id: str
    started_at: str
    sections_total: int = 0
    sections_processed: int = 0
    sections_skipped_cached: int = 0
    provider_calls: int = 0
    provider_retries: int = 0
    total_latency_ms: float = 0.0
    findings_total: int = 0
    integrity_checks_ok: int = 0
    integrity_checks_failed: int = 0
    finished_at: str | None = None

    def stop_timer(self) -> None:
        self.finished_at = utc_now_iso()


def timer_ms() -> float:
    return time.perf_counter() * 1000.0
