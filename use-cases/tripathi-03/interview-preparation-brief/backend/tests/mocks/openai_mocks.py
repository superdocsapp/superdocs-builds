"""Deterministic mock payloads for OpenAI structured outputs."""

from __future__ import annotations

from app.schemas.agent import ReportExtrasOutput, RoleSummaryOutput, SkillMatchOutput
from app.schemas.brief import RoadmapPhase, SkillItem, StarAnswer
from app.schemas.company import CompanyExtractionOutput
from app.schemas.questions import (
    Difficulty,
    InterviewQuestionItem,
    InterviewQuestionLLMOutput,
    RevisionLink,
)
from app.schemas.resume import (
    EducationItem,
    ExperienceItem,
    ResumeExtractionOutput,
)


def role_summary_output() -> RoleSummaryOutput:
    return RoleSummaryOutput(
        role_summary="Backend Engineer building reliable APIs.",
        required_skills=[
            SkillItem(name="Python"),
            SkillItem(name="FastAPI"),
            SkillItem(name="Kubernetes"),
        ],
    )


def skill_match_output(resume_snippet: str = "Built payment APIs with FastAPI") -> SkillMatchOutput:
    return SkillMatchOutput(
        matching_skills=[
            SkillItem(name="Python", evidence="Skills: Python, FastAPI, PostgreSQL, Docker"),
            SkillItem(name="FastAPI", evidence=resume_snippet),
        ],
        missing_skills=[SkillItem(name="Kubernetes")],
        gap_analysis_summary="Strong API background; Kubernetes gap.",
        resume_improvements=["Quantify API latency/throughput impact."],
        technical_topics=["Kubernetes"],
    )


def question_bank_output() -> InterviewQuestionLLMOutput:
    def q(text: str, difficulty: Difficulty = Difficulty.MEDIUM) -> InterviewQuestionItem:
        return InterviewQuestionItem(
            question=text,
            difficulty=difficulty,
            expected_answer="Describe approach with trade-offs.",
            resume_evidence="No evidence found.",
            missing_knowledge=["Depth in topic"],
            revision_links=[
                RevisionLink(title="Revise topic", url="https://revise.local/topic/overview")
            ],
        )

    return InterviewQuestionLLMOutput(
        technical_questions=[q("Explain FastAPI dependency injection.")] * 5,
        behavioral_questions=[q("Tell me about a time you handled ambiguity.")] * 5,
        company_specific_questions=[q("Why Acme?", Difficulty.EASY)] * 4,
        scenario_based_questions=[q("Latency spike response plan", Difficulty.HARD)] * 4,
        system_design_questions=[q("Design a rate limiter", Difficulty.HARD)] * 4,
        coding_questions=[q("Implement LRU cache")] * 4,
    )


def resume_extraction_output() -> ResumeExtractionOutput:
    return ResumeExtractionOutput(
        education=[
            EducationItem(
                institution="State University",
                degree="B.S. Computer Science",
                evidence="State University",
            )
        ],
        experience=[
            ExperienceItem(
                company="Acme Corp",
                title="Software Engineer",
                evidence="Acme Corp — Software Engineer (2020-2024)",
                responsibilities=["Built payment APIs with FastAPI and PostgreSQL."],
            )
        ],
        projects=[],
        skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
        achievements=[],
        technologies=["Python", "FastAPI", "PostgreSQL", "Docker"],
        years_of_experience=5,
        years_of_experience_explicitly_stated=True,
        years_of_experience_evidence="5+ years of experience in backend systems.",
    )


def company_extraction_output() -> CompanyExtractionOutput:
    return CompanyExtractionOutput(
        industry="Fintech",
        products=["Payments API"],
        mission="Make money movement reliable",
        tech_stack=["Python", "PostgreSQL"],
        interview_process="Unknown",
        engineering_culture="Unknown",
        latest_news=["Unknown"],
        tech_blogs=["Unknown"],
        hiring_trends="Unknown",
    )


def report_extras_output() -> ReportExtrasOutput:
    return ReportExtrasOutput(
        roadmap=[
            RoadmapPhase(phase="30", goals=["Map stories"], actions=["Draft STAR outlines"]),
            RoadmapPhase(phase="60", goals=["Deepen gaps"], actions=["Practice mocks"]),
            RoadmapPhase(phase="90", goals=["Polish"], actions=["Timed drills"]),
        ]
    )


def star_answer_no_evidence() -> StarAnswer:
    return StarAnswer(
        question="Tell me about a time you handled ambiguity.",
        has_evidence=False,
        note="No evidence found.",
    )
