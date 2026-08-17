from __future__ import annotations

from pydantic import BaseModel, Field


class DealTerms(BaseModel):
    project_name: str
    producer: str
    talent: str
    term: str
    territory: str
    media: list[str] = Field(default_factory=list)
    compensation: str
    deliverables: list[str] = Field(default_factory=list)
    exclusivity: str
    approval_rights: str
    credit: str
    termination: str


class GeneratedAgreement(BaseModel):
    markdown: str
    clause_checks: dict[str, bool]
    exported_docx: bytes | None = None
    session_id: str | None = None
    reviewed_changes: int = 0

    @property
    def is_complete(self) -> bool:
        return all(self.clause_checks.values())
