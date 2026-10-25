from typing import Any
from pydantic import BaseModel, Field


class RunSubmittalRequest(BaseModel):
    project_id: str = Field(default="BROD-2026")
    submittal_number: str = Field(default="SUB-001")
    specification_section: str | None = None
    scenario: str | None = None
    title: str | None = None
    specification_data: dict[str, Any] | None = None
    submission_data: dict[str, Any] | None = None


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    context_submittal_number: str | None = None


class Citation(BaseModel):
    source_type: str  # "SPECIFICATION", "SUBMITTAL", "FINDING", "REGISTER"
    identifier: str
    section: str | None = None
    excerpt: str


class ChatResponse(BaseModel):
    query: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)


class SearchResultItem(BaseModel):
    entity_type: str  # "SUBMITTAL", "FINDING", "TRANSMITTAL"
    entity_id: str
    title: str
    subtitle: str
    matched_text: str
    url: str


class SearchResponse(BaseModel):
    query: str
    total_count: int
    results: list[SearchResultItem]
