"""Pydantic models for grounded company research."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

UNKNOWN = "Unknown"


def _as_unknown_str(value: str | None) -> str:
    if value is None:
        return UNKNOWN
    cleaned = value.strip()
    if not cleaned:
        return UNKNOWN
    lowered = cleaned.lower()
    if lowered in {
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "not available",
        "unavailable",
        "not found",
        "no data",
    }:
        return UNKNOWN
    return cleaned


def _as_unknown_list(values: list[str] | None) -> list[str]:
    if not values:
        return [UNKNOWN]
    cleaned = [_as_unknown_str(v) for v in values]
    cleaned = [v for v in cleaned if v != UNKNOWN]
    return cleaned or [UNKNOWN]


class CompanyResearchRequest(BaseModel):
    company_name: str = Field(..., min_length=1, description="Target company name")
    company_url: str | None = Field(
        default=None,
        description="Optional official company URL used as the primary evidence source",
    )

    @field_validator("company_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("company_name is required")
        return cleaned

    @field_validator("company_url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not cleaned.startswith(("http://", "https://")):
            cleaned = f"https://{cleaned}"
        return cleaned


class CompanyResearchResponse(BaseModel):
    """Structured company research JSON. Unavailable fields are exactly 'Unknown'."""

    company_name: str
    industry: str = UNKNOWN
    products: list[str] = Field(default_factory=lambda: [UNKNOWN])
    mission: str = UNKNOWN
    tech_stack: list[str] = Field(default_factory=lambda: [UNKNOWN])
    interview_process: str = UNKNOWN
    engineering_culture: str = UNKNOWN
    latest_news: list[str] = Field(default_factory=lambda: [UNKNOWN])
    tech_blogs: list[str] = Field(default_factory=lambda: [UNKNOWN])
    hiring_trends: str = UNKNOWN
    sources: list[str] = Field(
        default_factory=list,
        description="URLs / evidence sources actually used",
    )
    overview: str = UNKNOWN

    @field_validator("industry", "mission", "interview_process", "engineering_culture", "hiring_trends", "overview")
    @classmethod
    def validate_str_fields(cls, value: str) -> str:
        return _as_unknown_str(value)

    @field_validator("products", "tech_stack", "latest_news", "tech_blogs")
    @classmethod
    def validate_list_fields(cls, value: list[str]) -> list[str]:
        return _as_unknown_list(value)

    def to_brief_overview(self) -> str:
        """Build a concise overview from known fields only."""
        lines: list[str] = [f"{self.company_name}"]
        if self.industry != UNKNOWN:
            lines.append(f"Industry: {self.industry}")
        if self.mission != UNKNOWN:
            lines.append(f"Mission: {self.mission}")
        if self.products != [UNKNOWN]:
            lines.append(f"Products: {', '.join(self.products)}")
        if self.tech_stack != [UNKNOWN]:
            lines.append(f"Tech stack: {', '.join(self.tech_stack)}")
        if self.engineering_culture != UNKNOWN:
            lines.append(f"Engineering culture: {self.engineering_culture}")
        if self.interview_process != UNKNOWN:
            lines.append(f"Interview process: {self.interview_process}")
        if self.latest_news != [UNKNOWN]:
            lines.append("Latest news: " + "; ".join(self.latest_news[:5]))
        if self.tech_blogs != [UNKNOWN]:
            lines.append("Tech blogs: " + "; ".join(self.tech_blogs[:5]))
        if self.hiring_trends != UNKNOWN:
            lines.append(f"Hiring trends: {self.hiring_trends}")

        if len(lines) == 1:
            return (
                f"{self.company_name}: insufficient public evidence was available. "
                "All research fields are Unknown."
            )
        return "\n".join(lines)


class CompanyExtractionOutput(BaseModel):
    """LLM extraction schema — values must come only from provided evidence."""

    industry: str = UNKNOWN
    products: list[str] = Field(default_factory=list)
    mission: str = UNKNOWN
    tech_stack: list[str] = Field(default_factory=list)
    interview_process: str = UNKNOWN
    engineering_culture: str = UNKNOWN
    latest_news: list[str] = Field(default_factory=list)
    tech_blogs: list[str] = Field(default_factory=list)
    hiring_trends: str = UNKNOWN
