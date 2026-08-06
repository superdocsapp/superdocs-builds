"""FastAPI integration tests with mocked LLM/DB — no live API keys."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_company_research_service,
    get_db,
    get_interview_report_service,
    get_question_generator,
    get_resume_analyzer_service,
)
from app.main import app
from app.schemas.company import UNKNOWN, CompanyResearchResponse
from app.schemas.resume import EmbeddingInfo, ResumeAnalysis, ResumeAnalyzerResponse
from app.services.questions.generator import InterviewQuestionGenerator
from app.services.report.service import InterviewReportService
from tests.mocks.openai_mocks import question_bank_output


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    async def _noop_lifecycle() -> None:
        return None

    monkeypatch.setattr("app.main.init_database", _noop_lifecycle)
    monkeypatch.setattr("app.main.dispose_engine", _noop_lifecycle)

    async def _override_db():
        session = AsyncMock()
        session.execute = AsyncMock(return_value=None)
        yield session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_endpoint(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_endpoint(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Interview Preparation Brief" in response.json()["service"]


def test_company_research_endpoint_mocked(client: TestClient):
    class FakeCompanyService:
        async def research_structured(self, request):  # noqa: ANN001
            return CompanyResearchResponse(
                company_name=request.company_name,
                industry=UNKNOWN,
                products=[UNKNOWN],
                mission=UNKNOWN,
                tech_stack=[UNKNOWN],
                interview_process=UNKNOWN,
                engineering_culture=UNKNOWN,
                latest_news=[UNKNOWN],
                tech_blogs=[UNKNOWN],
                hiring_trends=UNKNOWN,
                sources=[],
            )

    app.dependency_overrides[get_company_research_service] = lambda: FakeCompanyService()
    response = client.post("/api/v1/company/research", json={"company_name": "Acme"})
    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] == "Acme"
    assert body["industry"] == "Unknown"


def test_questions_generate_endpoint_mocked(client: TestClient, mock_llm, sample_resume, sample_jd):
    mock_llm.set_structured("InterviewQuestionLLMOutput", question_bank_output())
    app.dependency_overrides[get_question_generator] = lambda: InterviewQuestionGenerator()
    response = client.post(
        "/api/v1/questions/generate",
        json={
            "resume_text": sample_resume,
            "jd_text": sample_jd,
            "company_name": "Acme",
            "company_data": {"industry": "Fintech"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["all"] >= 20
    first = body["question_bank"]["technical_questions"][0]
    for key in (
        "difficulty",
        "expected_answer",
        "resume_evidence",
        "missing_knowledge",
        "revision_links",
    ):
        assert key in first


def test_reports_generate_and_export_markdown(client: TestClient):
    service = InterviewReportService(db=None)
    app.dependency_overrides[get_interview_report_service] = lambda: service

    payload = {
        "company_name": "Acme",
        "company_overview": "Payments company",
        "role_summary": "Backend Engineer",
        "matching_skills": [{"name": "Python", "evidence": "Skills: Python"}],
        "missing_skills": [{"name": "Kubernetes"}],
        "required_skills": [{"name": "Python"}, {"name": "Kubernetes"}],
        "resume_improvements": ["Add metrics"],
        "likely_interview_questions": ["Explain REST"],
        "evidence_backed_answers": [],
        "star_answers": [],
    }
    generated = client.post("/api/v1/reports/generate", json=payload)
    assert generated.status_code == 200
    report = generated.json()["report"]
    assert report["resume_match_score"]["score"] == 50

    exported = client.post("/api/v1/reports/export?format=markdown", json=report)
    assert exported.status_code == 200
    assert "text/markdown" in exported.headers["content-type"]
    assert b"Interview Preparation Report" in exported.content


def test_reports_export_pdf(client: TestClient):
    service = InterviewReportService(db=None)
    app.dependency_overrides[get_interview_report_service] = lambda: service
    generated = client.post(
        "/api/v1/reports/generate",
        json={
            "company_name": "Acme",
            "company_overview": "Overview",
            "role_summary": "Role",
            "matching_skills": [],
            "missing_skills": [],
        },
    )
    report = generated.json()["report"]
    exported = client.post("/api/v1/reports/export?format=pdf", json=report)
    assert exported.status_code == 200
    assert exported.content[:4] == b"%PDF"


def test_resume_analyze_text_mocked(client: TestClient, sample_resume):
    class FakeAnalyzer:
        async def analyze_text(self, **kwargs):  # noqa: ANN003
            return ResumeAnalyzerResponse(
                candidate_name=kwargs.get("candidate_name"),
                analysis=ResumeAnalysis(
                    skills=["Python", "FastAPI"],
                    technologies=["Python", "FastAPI"],
                    years_of_experience=5.0,
                    years_of_experience_evidence="5+ years of experience in backend systems.",
                ),
                embeddings=EmbeddingInfo(
                    session_id=uuid4(),
                    document_id=uuid4(),
                    chunk_count=3,
                    embedding_model="text-embedding-3-small",
                    dimensions=1536,
                ),
                resume_char_count=len(kwargs["resume_text"]),
            )

    app.dependency_overrides[get_resume_analyzer_service] = lambda: FakeAnalyzer()
    response = client.post(
        "/api/v1/resume/analyze-text",
        json={"resume_text": sample_resume, "candidate_name": "Jane Doe"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["years_of_experience"] == 5.0
    assert body["embeddings"]["chunk_count"] == 3
