"""Additional backend unit tests with mocked OpenAI."""

from __future__ import annotations

import pytest

from app.schemas.brief import SkillItem
from app.schemas.questions import InterviewQuestionRequest
from app.schemas.report import ReportGenerateRequest
from app.services.questions.generator import InterviewQuestionGenerator
from app.services.report.assembler import ReportAssembler
from app.services.report.exporters.html_exporter import to_html
from app.services.report.exporters.pdf_exporter import to_pdf_bytes
from tests.mocks.openai_mocks import question_bank_output


@pytest.mark.asyncio
async def test_question_generator_with_mocked_openai(mock_llm, sample_resume, sample_jd):
    mock_llm.set_structured("InterviewQuestionLLMOutput", question_bank_output())
    result = await InterviewQuestionGenerator().generate(
        InterviewQuestionRequest(
            resume_text=sample_resume,
            jd_text=sample_jd,
            company_name="Acme",
            company_data={"industry": "Fintech"},
        )
    )
    assert result.totals["technical_questions"] >= 4
    assert result.totals["behavioral_questions"] >= 4
    assert result.totals["coding_questions"] >= 4
    item = result.question_bank.technical_questions[0]
    assert item.difficulty.value in {"Easy", "Medium", "Hard"}
    assert item.revision_links


def test_html_and_pdf_export_without_network():
    report = ReportAssembler().assemble(
        ReportGenerateRequest(
            company_name="Acme",
            company_overview="Overview text",
            role_summary="Backend Engineer",
            matching_skills=[SkillItem(name="Python", evidence="Python")],
            missing_skills=[SkillItem(name="Kubernetes")],
        )
    )
    html = to_html(report)
    assert "Interview Preparation Report" in html
    assert "Acme" in html

    pdf = to_pdf_bytes(report)
    assert pdf[:4] == b"%PDF"
