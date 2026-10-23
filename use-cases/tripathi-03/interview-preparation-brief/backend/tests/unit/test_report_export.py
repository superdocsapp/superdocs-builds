"""Unit tests for report assembly and markdown export."""

from app.schemas.brief import SkillItem
from app.schemas.report import ReportGenerateRequest
from app.services.report.assembler import ReportAssembler
from app.services.report.exporters.markdown_exporter import to_markdown


def test_assemble_computes_match_score_and_sections():
    report = ReportAssembler().assemble(
        ReportGenerateRequest(
            company_name="Acme",
            company_overview="Acme builds payments APIs.",
            role_summary="Backend Engineer focused on APIs.",
            matching_skills=[
                SkillItem(name="Python", evidence="Used Python at Acme"),
                SkillItem(name="FastAPI", evidence="Built FastAPI services"),
            ],
            missing_skills=[SkillItem(name="Kubernetes")],
            required_skills=[
                SkillItem(name="Python"),
                SkillItem(name="FastAPI"),
                SkillItem(name="Kubernetes"),
            ],
            resume_improvements=["Add metrics to API project bullet"],
            technical_topics=["Kubernetes"],
            likely_interview_questions=["Explain REST versioning"],
            evidence_backed_answers=[],
            star_answers=[],
        )
    )
    assert report.cover_page.company_name == "Acme"
    assert report.resume_match_score.score == 67
    assert any("Python" in s for s in report.strengths)
    assert any("Kubernetes" in w for w in report.weaknesses)
    assert report.revision_plan
    assert report.day_30_60_90_plan
    assert report.final_recommendations


def test_markdown_export_contains_required_headings():
    report = ReportAssembler().assemble(
        ReportGenerateRequest(
            company_name="Acme",
            company_overview="Overview",
            role_summary="Role",
            matching_skills=[SkillItem(name="Python", evidence="Python")],
            missing_skills=[],
        )
    )
    md = to_markdown(report)
    for heading in [
        "# Interview Preparation Report",
        "## Company Overview",
        "## Role Summary",
        "## Resume Match Score",
        "## Strengths",
        "## Weaknesses",
        "## Skill Gap",
        "## Resume Improvements",
        "## Interview Questions",
        "## Evidence-backed Answers",
        "## Behavioral Answers",
        "## STAR Stories",
        "## Revision Plan",
        "## 30-60-90 Day Plan",
        "## Final Recommendations",
    ]:
        assert heading in md
