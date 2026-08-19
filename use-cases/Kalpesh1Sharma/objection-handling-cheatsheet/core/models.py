from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EntryStatus(str, Enum):
    COMPLETE = "complete"
    MISSING_RESPONSE = "missing_response"
    NEEDS_REVIEW = "needs_review"


class SourceUnit(BaseModel):
    """
    One ordered piece of source text.

    IDs make it possible to prove which source content
    produced each cheatsheet entry.
    """

    source_id: str
    position: int
    text: str


class ObjectionEntry(BaseModel):
    entry_id: str

    objection: str
    response: str | None = None

    status: EntryStatus

    objection_source_ids: list[str] = Field(
        default_factory=list
    )

    response_source_ids: list[str] = Field(
        default_factory=list
    )


class ParseResult(BaseModel):
    entries: list[ObjectionEntry] = Field(
        default_factory=list
    )

    source_units: list[SourceUnit] = Field(
        default_factory=list
    )

    detected_objection_source_ids: list[str] = Field(
    default_factory=list
    )

    unassigned_source_ids: list[str] = Field(
        default_factory=list
    )

    warnings: list[str] = Field(
        default_factory=list
    )

    @property
    def objection_count(self) -> int:
        return len(self.entries)

    @property
    def complete_count(self) -> int:
        return sum(
            entry.status == EntryStatus.COMPLETE
            for entry in self.entries
        )

    @property
    def missing_response_count(self) -> int:
        return sum(
            entry.status
            == EntryStatus.MISSING_RESPONSE
            for entry in self.entries
        )