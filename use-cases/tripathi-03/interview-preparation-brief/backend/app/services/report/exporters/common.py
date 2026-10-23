"""Shared helpers for rendering Interview Preparation Report sections."""

from __future__ import annotations

from typing import Any

from app.schemas.report import InterviewPreparationReportDocument


def iter_question_groups(report: InterviewPreparationReportDocument) -> list[tuple[str, list[Any]]]:
    bank = report.interview_questions
    if hasattr(bank, "model_dump"):
        data = bank.model_dump()
    elif isinstance(bank, dict):
        data = bank
    else:
        data = {}

    mapping = [
        ("Technical Questions", data.get("technical_questions") or []),
        ("Behavioral Questions", data.get("behavioral_questions") or []),
        ("Company Specific Questions", data.get("company_specific_questions") or []),
        ("Scenario Based Questions", data.get("scenario_based_questions") or []),
        ("System Design Questions", data.get("system_design_questions") or []),
        ("Coding Questions", data.get("coding_questions") or []),
    ]
    return [(title, items) for title, items in mapping if items]


def question_fields(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        item = item.model_dump()
    if not isinstance(item, dict):
        return {
            "question": str(item),
            "difficulty": "Medium",
            "expected_answer": "No evidence found.",
            "resume_evidence": "No evidence found.",
            "missing_knowledge": [],
            "revision_links": [],
        }
    return {
        "question": item.get("question", ""),
        "difficulty": item.get("difficulty", "Medium"),
        "expected_answer": item.get("expected_answer", "No evidence found."),
        "resume_evidence": item.get("resume_evidence", "No evidence found."),
        "missing_knowledge": item.get("missing_knowledge") or [],
        "revision_links": item.get("revision_links") or [],
    }


def safe_filename(company_name: str, ext: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in company_name.lower()).strip("-")
    slug = slug or "interview-report"
    return f"{slug}-interview-preparation-report.{ext}"
