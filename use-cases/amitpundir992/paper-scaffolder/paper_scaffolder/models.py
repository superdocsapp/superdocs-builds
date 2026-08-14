"""Typed domain models for the Paper Scaffolder."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class SectionStatus(StrEnum):
    """Whether a manuscript section can be safely populated."""

    AVAILABLE = "available"
    GENERATED = "generated"
    INSUFFICIENT_INFORMATION = "insufficient_information"


@dataclass(frozen=True)
class PaperInputs:
    """Information supplied directly by the researcher."""

    research_question: str
    methodology: str
    dataset_description: str
    journal_template: str


@dataclass(frozen=True)
class ManuscriptSection:
    """One section in a manuscript skeleton."""

    section_id: str
    title: str
    semantic_role: str
    status: SectionStatus
    content: str
    reason: str
    available_sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ManuscriptSkeleton:
    """A journal-derived, ordered manuscript skeleton."""

    manuscript_id: str
    journal_template: str
    sections: tuple[ManuscriptSection, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manuscript_id": self.manuscript_id,
            "journal_template": self.journal_template,
            "sections": [section.to_dict() for section in self.sections],
        }


@dataclass(frozen=True)
class SectionGenerationResult:
    """Result of attempting to populate one section."""

    manuscript_id: str
    section: ManuscriptSection

    def to_dict(self) -> dict[str, Any]:
        return {
            "manuscript_id": self.manuscript_id,
            "section": self.section.to_dict(),
        }
