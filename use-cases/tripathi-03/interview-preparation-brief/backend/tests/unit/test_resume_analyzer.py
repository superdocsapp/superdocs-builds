"""Unit tests for Resume Analyzer grounding rules."""

from app.schemas.resume import (
    AchievementItem,
    EducationItem,
    ExperienceItem,
    ResumeExtractionOutput,
)
from app.services.resume.analyzer import ResumeAnalyzerService


class _FakeDB:
    pass


def _service() -> ResumeAnalyzerService:
    # DB is unused by normalize helpers
    return ResumeAnalyzerService(db=_FakeDB())  # type: ignore[arg-type]


def test_drops_entries_without_evidence_in_resume():
    resume = "Acme Corp — Software Engineer. Built APIs with FastAPI."
    extraction = ResumeExtractionOutput(
        experience=[
            ExperienceItem(
                company="Acme Corp",
                title="Software Engineer",
                evidence="Acme Corp — Software Engineer",
                responsibilities=["Built APIs with FastAPI"],
            ),
            ExperienceItem(
                company="Invented Inc",
                title="CTO",
                evidence="Invented Inc CTO 2010-2020",
                responsibilities=["Led everything"],
            ),
        ],
        education=[
            EducationItem(
                institution="Fake University",
                degree="PhD",
                evidence="PhD Fake University",
            )
        ],
        skills=["FastAPI", "QuantumTeleportation"],
        technologies=["FastAPI"],
        achievements=[
            AchievementItem(
                description="Reduced latency 40%",
                evidence="Reduced latency by inventing magic",
            )
        ],
        years_of_experience=12,
        years_of_experience_explicitly_stated=True,
        years_of_experience_evidence="12 years of experience",
    )
    analysis = _service()._normalize_analysis(extraction, resume)
    assert len(analysis.experience) == 1
    assert analysis.experience[0].company == "Acme Corp"
    assert analysis.education == []
    assert analysis.skills == ["FastAPI"]
    assert "QuantumTeleportation" not in analysis.skills
    assert analysis.achievements == []
    assert analysis.years_of_experience is None


def test_explicit_years_pattern_extracted():
    resume = "Jane Doe. 5+ years of experience in backend systems. Skills: Python."
    extraction = ResumeExtractionOutput(
        skills=["Python"],
        years_of_experience=None,
        years_of_experience_explicitly_stated=False,
    )
    analysis = _service()._normalize_analysis(extraction, resume)
    assert analysis.years_of_experience == 5.0
    assert analysis.years_of_experience_evidence
    assert "years" in analysis.years_of_experience_evidence.lower()


def test_no_years_when_not_supported():
    resume = "Worked at Acme as Engineer from 2020 to 2022."
    extraction = ResumeExtractionOutput(
        experience=[
            ExperienceItem(
                company="Acme",
                title="Engineer",
                start_date="2020",
                end_date="2022",
                evidence="Worked at Acme as Engineer from 2020 to 2022.",
            )
        ],
        years_of_experience=2,
        years_of_experience_explicitly_stated=False,
        years_of_experience_evidence=None,
    )
    analysis = _service()._normalize_analysis(extraction, resume)
    # Must not calculate/infer years from date ranges alone
    assert analysis.years_of_experience is None
    assert len(analysis.experience) == 1
