"""Data model shared across the amendment-qna-delta-applier pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class SourceRef:
    """Points at the exact place a fact came from, for citation/traceability."""

    document: str
    paragraph_id: str
    paragraph_text: str

    def citation(self) -> str:
        return f"{self.document} {self.paragraph_id}"


@dataclass(frozen=True)
class ParsedFact:
    """One atomic fact extracted from a source document, before diffing."""

    rule_type: str
    key: str
    value: Any
    change_kind: str  # "baseline" | "modified" | "added" | "deleted" | "clarified" | "confirmed_no_change"
    source: SourceRef


@dataclass(frozen=True)
class AmendmentDelta:
    """A change between the solicitation baseline and an incoming document."""

    delta_id: str
    rule_type: str
    key: str
    old_value: Any
    new_value: Any
    change_kind: str  # "modified" | "added" | "deleted" | "clarified"
    source: SourceRef


@dataclass(frozen=True)
class Confirmation:
    """An incoming document explicitly confirmed a fact is unchanged, and it is."""

    rule_type: str
    key: str
    value: Any
    source: SourceRef


@dataclass(frozen=True)
class Conflict:
    """An incoming document contradicts the currently-tracked state.

    Never silently resolved: surfaced for a human to adjudicate.
    """

    rule_type: str
    key: str
    existing_value: Any
    existing_source: Optional[SourceRef]
    new_value: Any
    new_source: SourceRef


@dataclass
class SectionImpact:
    """A proposal section affected by one or more amendment deltas."""

    section_id: str
    order: str  # "direct" | "second_order"
    deltas: list = field(default_factory=list)
    caused_by_section: Optional[str] = None


@dataclass
class ReviewItem:
    """A staged edit awaiting human approval, with its full citation trail."""

    change_id: str
    job_id: str
    session_id: str
    section_id: str
    operation: str
    old_html: Optional[str]
    new_html: Optional[str]
    ai_explanation: str
    deltas: list = field(default_factory=list)
    approved: Optional[bool] = None
    feedback: Optional[str] = None
    decided_at: Optional[str] = None
