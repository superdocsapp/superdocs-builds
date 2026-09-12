from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class SectionStatus(str, Enum):
    EMPTY = "empty"
    DRAFTED = "drafted"
    FLAGGED = "flagged"
    VERIFIED = "verified"


class Citation(BaseModel):
    id: str
    section_id: str
    source_id: str
    claim_text: str
    passage_ref: str
    verified: bool = False


class Section(BaseModel):
    id: str
    paper_id: str
    title: str
    order: int
    content: str = ""
    content_hash: str = ""
    citations: list[Citation] = Field(default_factory=list)
    status: SectionStatus = SectionStatus.EMPTY

    def set_content(self, content: str) -> None:
        """The only way section content should ever be mutated.
        Content and content_hash can never drift out of sync
        because they're always written together."""
        self.content = content
        self.content_hash = self._compute_hash(content)
        self.status = SectionStatus.DRAFTED

    @staticmethod
    def _compute_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SourceChunk(BaseModel):
    chunk_id: str
    text: str
    embedding: Optional[list[float]] = None


class Source(BaseModel):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    raw_text: str
    chunks: list[SourceChunk] = Field(default_factory=list)


class PaperStatus(str, Enum):
    OUTLINING = "outlining"
    DRAFTING = "drafting"
    VERIFYING = "verifying"
    EXPORTED = "exported"


class Paper(BaseModel):
    id: str
    topic: str
    session_id: Optional[str] = None
    status: PaperStatus = PaperStatus.OUTLINING
    sections: list[Section] = Field(default_factory=list)
    bibliography: list[Source] = Field(default_factory=list)

    def get_section(self, section_id: str) -> Section:
        for s in self.sections:
            if s.id == section_id:
                return s
        raise KeyError(f"No section with id {section_id}")

    def snapshot_all_hashes(self) -> dict[str, str]:
        """Call this immediately before any revision."""
        return {s.id: s.content_hash for s in self.sections}

    def diff_against(self, snapshot: dict[str, str]) -> list[str]:
        """Call this after a revision. Returns the section IDs
        whose hash changed — this list should equal exactly
        the section(s) you intended to touch, nothing more."""
        return [s.id for s in self.sections if snapshot.get(s.id) != s.content_hash]


class RunAction(str, Enum):
    DRAFT = "draft"
    REVISE = "revise"
    VERIFY = "verify"
    EXPORT = "export"


class RunLog(BaseModel):
    run_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action: RunAction
    sections_touched: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0
