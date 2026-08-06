"""Shared LangGraph state passed between all workflow nodes."""

from __future__ import annotations

from typing import Any, TypedDict


class BriefState(TypedDict, total=False):
    # ---- Pipeline identity / raw inputs ----
    session_id: str
    brief_id: str
    company_name: str
    company_url: str | None
    resume_text: str
    jd_text: str
    resume_document_id: str
    jd_document_id: str
    evidence_fallback: str

    # ---- ResumeParser ----
    resume_normalized: str
    resume_char_count: int

    # ---- JDParser ----
    role_summary: str
    required_skills: list[dict[str, Any]]

    # ---- CompanyResearch ----
    company_overview: str
    company_context: str
    company_profile: dict[str, Any]

    # ---- SkillGapAnalysis ----
    matching_skills: list[dict[str, Any]]
    missing_skills: list[dict[str, Any]]
    gap_analysis_summary: str
    resume_improvements: list[str]
    technical_topics: list[str]

    # ---- QuestionGeneration ----
    likely_interview_questions: list[str]
    company_specific_questions: list[str]
    behavioural_questions: list[str]
    question_bank: dict[str, Any]

    # ---- AnswerGeneration ----
    evidence_backed_answers: list[dict[str, Any]]
    star_answers: list[dict[str, Any]]

    # ---- InterviewPreparationReport ----
    roadmap: list[dict[str, Any]]
    report: dict[str, Any]

    # ---- Control ----
    current_step: str
    error: str | None
