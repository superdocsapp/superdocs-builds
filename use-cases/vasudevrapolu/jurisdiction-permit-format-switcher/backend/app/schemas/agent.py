from pydantic import BaseModel, Field
from typing import Literal

class SourceDocument(BaseModel):
    name: str
    text: str
    source_type: str = "text"

class Rule(BaseModel):
    id: str
    statement: str
    severity: Literal["info", "warning", "blocking"] = "warning"

class StartRunRequest(BaseModel):
    documents: list[SourceDocument] = Field(min_length=1)
    rules: list[Rule] = []

class Decision(BaseModel):
    id: str
    kind: Literal["conflict", "finding", "update"]
    approved: bool
    feedback: str | None = None

class ApprovalRequest(BaseModel):
    decisions: list[Decision]
