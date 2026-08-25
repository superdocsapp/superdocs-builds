from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


def _trim(value: str) -> str:
    return value.strip()


IdValue = Annotated[str, Field(min_length=1, max_length=256)]


class Author(Schema):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=200)

    _trim_id = field_validator("id", mode="before")(_trim)
    _trim_name = field_validator("name", mode="before")(_trim)


class AnalyzeRequest(Schema):
    authors: list[Author] = Field(min_length=1, max_length=100)
    contributions: str = Field(min_length=1, max_length=50_000)
    funding: str = Field(default="", max_length=50_000)
    conflicts: str = Field(default="", max_length=50_000)

    _trim_contributions = field_validator("contributions", mode="before")(_trim)
    _trim_funding = field_validator("funding", mode="before")(_trim)
    _trim_conflicts = field_validator("conflicts", mode="before")(_trim)


class Contribution(Schema):
    authorId: str = Field(min_length=1, max_length=256)
    evidence: str = Field(max_length=10_000)
    roleIds: list[IdValue] = Field(default_factory=list, max_length=14)
    status: Literal["approved", "ambiguous"] = "approved"

    _trim_author = field_validator("authorId", mode="before")(_trim)
    _trim_evidence = field_validator("evidence", mode="before")(_trim)
    _trim_roles = field_validator("roleIds", mode="before")(lambda roles: [role.strip() for role in roles] if isinstance(roles, list) else roles)


class AnalysisContribution(Schema):
    authorId: str = Field(min_length=1, max_length=256)
    evidence: str = Field(max_length=10_000)
    roleIds: list[IdValue] = Field(default_factory=list, max_length=14)
    status: Literal["proposed", "ambiguous", "unsupported"] = "ambiguous"

    _trim_author = field_validator("authorId", mode="before")(_trim)
    _trim_evidence = field_validator("evidence", mode="before")(_trim)
    _trim_roles = field_validator("roleIds", mode="before")(lambda roles: [role.strip() for role in roles] if isinstance(roles, list) else roles)


class Funding(Schema):
    status: Literal["reported", "none", "unknown"]
    funder: str | None = Field(default=None, max_length=500)
    awardNumber: str | None = Field(default=None, max_length=500)
    evidence: str = Field(default="", max_length=10_000)

    _trim_funder = field_validator("funder", mode="before")(lambda value: _trim(value) if value is not None else value)
    _trim_award = field_validator("awardNumber", mode="before")(lambda value: _trim(value) if value is not None else value)
    _trim_evidence = field_validator("evidence", mode="before")(_trim)


class ConflictItem(Schema):
    authorId: str | None = Field(default=None, max_length=256)
    disclosure: str | None = Field(default=None, max_length=2_000)
    evidence: str = Field(default="", max_length=10_000)

    _trim_author = field_validator("authorId", mode="before")(lambda value: _trim(value) if value is not None else value)
    _trim_disclosure = field_validator("disclosure", mode="before")(lambda value: _trim(value) if value is not None else value)
    _trim_evidence = field_validator("evidence", mode="before")(_trim)


class Conflicts(Schema):
    status: Literal["reported", "none", "unknown"]
    items: list[ConflictItem] = Field(default_factory=list, max_length=100)


class StatementRequest(Schema):
    authors: list[Author] = Field(min_length=1, max_length=100)
    contributions: list[Contribution] = Field(max_length=500)
    funding: Funding
    conflicts: Conflicts


class AnalysisProviderResponse(Schema):
    contributions: list[AnalysisContribution] = Field(default_factory=list, max_length=500)
    funding: Funding = Field(default_factory=lambda: Funding(status="unknown"))
    conflicts: Conflicts = Field(default_factory=lambda: Conflicts(status="unknown"))


SESSION_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class UploadRequest(Schema):
    sessionId: str = Field(min_length=1, max_length=256)
    filename: str = Field(min_length=1, max_length=512)
    fileBase64: str = Field(min_length=1, max_length=28_000_000)
    returnHtml: bool = True

    _trim_session = field_validator("sessionId", mode="before")(_trim)
    _trim_filename = field_validator("filename", mode="before")(_trim)

    @model_validator(mode="after")
    def valid_session_id(self):
        if not SESSION_ID.fullmatch(self.sessionId):
            raise ValueError("sessionId contains unsupported characters")
        return self


class ApplyRequest(Schema):
    sessionId: str = Field(min_length=1, max_length=256)
    facts: StatementRequest
    documentHtml: str | None = Field(default=None, min_length=1, max_length=50_000_000)
    approvalMode: Literal["approve_all", "ask_every_time"] = "ask_every_time"

    _trim_session = field_validator("sessionId", mode="before")(_trim)
    _trim_html = field_validator("documentHtml", mode="before")(lambda value: _trim(value) if value is not None else value)

    @model_validator(mode="after")
    def valid_session_id(self):
        if not SESSION_ID.fullmatch(self.sessionId):
            raise ValueError("sessionId contains unsupported characters")
        return self


class Change(Schema):
    changeId: str = Field(min_length=1, max_length=256)
    approved: bool
    feedback: str | None = Field(default=None, max_length=2_000)

    _trim_change = field_validator("changeId", mode="before")(_trim)


class ApproveRequest(Schema):
    sessionId: str = Field(min_length=1, max_length=256)
    jobId: str | None = Field(default=None, max_length=256)
    approved: bool
    feedback: str | None = Field(default=None, max_length=2_000)
    changes: list[Change] | None = Field(default=None, max_length=100)

    _trim_session = field_validator("sessionId", mode="before")(_trim)
    _trim_job = field_validator("jobId", mode="before")(lambda value: _trim(value) if value is not None else value)

    @model_validator(mode="after")
    def valid_session_id(self):
        if not SESSION_ID.fullmatch(self.sessionId):
            raise ValueError("sessionId contains unsupported characters")
        return self


class ExportRequest(Schema):
    sessionId: str | None = Field(default=None, max_length=256)
    documentHtml: str | None = Field(default=None, min_length=1, max_length=50_000_000)
    format: Literal["doc", "docx", "pdf", "html", "markdown", "txt"] = "docx"
    filename: str | None = Field(default=None, min_length=1, max_length=255)

    _trim_session = field_validator("sessionId", mode="before")(lambda value: _trim(value) if value is not None else value)
    _trim_format = field_validator("format", mode="before")(_trim)
    _trim_filename = field_validator("filename", mode="before")(lambda value: _trim(value) if value is not None else value)
    _trim_html = field_validator("documentHtml", mode="before")(lambda value: _trim(value) if value is not None else value)

    @model_validator(mode="after")
    def session_or_html(self):
        if not self.sessionId and not self.documentHtml:
            raise ValueError("sessionId or documentHtml is required")
        if self.sessionId and not SESSION_ID.fullmatch(self.sessionId):
            raise ValueError("sessionId contains unsupported characters")
        return self
