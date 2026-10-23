"""Tests for company research Unknown normalization (no hallucination path)."""

import pytest

from app.schemas.company import (
    UNKNOWN,
    CompanyExtractionOutput,
    CompanyResearchRequest,
    CompanyResearchResponse,
)
from app.services.company.company_research import CompanyResearchService


def test_unknown_response_when_no_evidence():
    service = CompanyResearchService()
    result = service._unknown_response("Acme Corp", sources=[])
    assert result.company_name == "Acme Corp"
    assert result.industry == UNKNOWN
    assert result.products == [UNKNOWN]
    assert result.mission == UNKNOWN
    assert result.tech_stack == [UNKNOWN]
    assert result.interview_process == UNKNOWN
    assert result.engineering_culture == UNKNOWN
    assert result.latest_news == [UNKNOWN]
    assert result.tech_blogs == [UNKNOWN]
    assert result.hiring_trends == UNKNOWN
    assert "Unknown" in result.overview or "insufficient" in result.overview.lower()


def test_normalize_maps_empty_and_na_to_unknown():
    service = CompanyResearchService()
    extraction = CompanyExtractionOutput(
        industry="n/a",
        products=[],
        mission="",
        tech_stack=["  ", "None"],
        interview_process="not available",
        engineering_culture="Unknown",
        latest_news=[],
        tech_blogs=["Python"],
        hiring_trends="Hiring backend engineers",
    )
    result = service._normalize_response(
        company_name="Example",
        extraction=extraction,
        sources=["https://example.com"],
    )
    assert result.industry == UNKNOWN
    assert result.products == [UNKNOWN]
    assert result.mission == UNKNOWN
    assert result.tech_stack == [UNKNOWN]
    assert result.interview_process == UNKNOWN
    assert result.engineering_culture == UNKNOWN
    assert result.latest_news == [UNKNOWN]
    assert result.tech_blogs == ["Python"]
    assert result.hiring_trends == "Hiring backend engineers"
    assert result.sources == ["https://example.com"]


def test_request_requires_company_name():
    with pytest.raises(Exception):
        CompanyResearchRequest(company_name="  ")


def test_response_json_shape():
    payload = CompanyResearchResponse(company_name="TestCo").model_dump()
    expected_keys = {
        "company_name",
        "industry",
        "products",
        "mission",
        "tech_stack",
        "interview_process",
        "engineering_culture",
        "latest_news",
        "tech_blogs",
        "hiring_trends",
        "sources",
        "overview",
    }
    assert expected_keys.issubset(payload.keys())
