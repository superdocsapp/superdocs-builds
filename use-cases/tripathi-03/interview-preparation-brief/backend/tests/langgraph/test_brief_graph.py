"""LangGraph workflow tests with mocked LLM — no live API keys."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.agents.graph import NODE_ORDER, build_brief_graph, build_validated_brief_graph
from app.agents.nodes.resume_parser import ResumeParser
from app.agents.state import BriefState
from tests.mocks.openai_mocks import (
    question_bank_output,
    role_summary_output,
    skill_match_output,
)


def test_node_order_contract():
    assert NODE_ORDER == [
        "ResumeParser",
        "JDParser",
        "CompanyResearch",
        "SkillGapAnalysis",
        "QuestionGeneration",
        "AnswerGeneration",
        "InterviewPreparationReport",
    ]


def test_compiled_graphs_expose_all_nodes():
    for builder in (build_brief_graph, build_validated_brief_graph):
        graph = builder()
        names = set(graph.get_graph().nodes)
        for node in NODE_ORDER:
            assert node in names


@pytest.mark.asyncio
async def test_resume_parser_node_validates_and_normalizes(sample_resume: str):
    node = ResumeParser()
    state: BriefState = {
        "session_id": str(uuid4()),
        "resume_text": sample_resume + "\n\n\n",
    }
    updated = await node(state)
    assert updated["current_step"] == "ResumeParser"
    assert updated["resume_char_count"] > 0
    assert "FastAPI" in updated["resume_normalized"]


@pytest.mark.asyncio
async def test_jd_parser_uses_mocked_structured_output(mock_llm, sample_jd: str):
    from app.agents.nodes.jd_parser import JDParser

    mock_llm.set_structured("RoleSummaryOutput", role_summary_output())
    node = JDParser()
    state: BriefState = {
        "session_id": str(uuid4()),
        "jd_text": sample_jd,
    }
    updated = await node(state)
    assert updated["current_step"] == "JDParser"
    assert "Backend Engineer" in updated["role_summary"]
    assert any(s["name"] == "Python" for s in updated["required_skills"])


@pytest.mark.asyncio
async def test_skill_gap_analysis_demotes_unevidenced_matches(mock_llm, sample_resume: str, sample_jd: str):
    from app.agents.nodes.skill_gap_analysis import SkillGapAnalysis

    mock_llm.set_structured("SkillMatchOutput", skill_match_output())
    node = SkillGapAnalysis()
    state: BriefState = {
        "session_id": str(uuid4()),
        "resume_normalized": sample_resume,
        "jd_text": sample_jd,
        "role_summary": "Backend Engineer",
        "required_skills": [
            {"name": "Python"},
            {"name": "FastAPI"},
            {"name": "Kubernetes"},
        ],
    }
    updated = await node(state)
    assert updated["current_step"] == "SkillGapAnalysis"
    assert any(s["name"] == "FastAPI" for s in updated["matching_skills"])
    assert any(s["name"] == "Kubernetes" for s in updated["missing_skills"])


@pytest.mark.asyncio
async def test_question_generation_node_with_mocked_generator(mock_llm, sample_resume: str, sample_jd: str):
    from app.agents.nodes.question_generation import QuestionGeneration

    mock_llm.set_structured("InterviewQuestionLLMOutput", question_bank_output())
    node = QuestionGeneration()
    state: BriefState = {
        "session_id": str(uuid4()),
        "company_name": "Acme",
        "company_overview": "Acme builds payments APIs.",
        "role_summary": "Backend Engineer",
        "required_skills": [],
        "matching_skills": [],
        "missing_skills": [],
        "jd_text": sample_jd,
        "resume_normalized": sample_resume,
    }
    updated = await node(state)
    assert updated["current_step"] == "QuestionGeneration"
    assert len(updated["likely_interview_questions"]) == 20
    assert updated["company_specific_questions"]
    assert updated["behavioural_questions"]
    assert updated.get("question_bank")


@pytest.mark.asyncio
async def test_validated_graph_runs_with_fully_mocked_nodes(sample_resume: str, sample_jd: str):
    """End-to-end graph smoke test — every node stubbed, no network/DB/LLM."""

    async def passthrough(name: str):
        async def _node(state: BriefState) -> BriefState:
            update = {**state, "current_step": name, "error": None}
            if name == "InterviewPreparationReport":
                update["report"] = {
                    "company_overview": state.get("company_overview", "Acme"),
                    "role_summary": state.get("role_summary", "Backend Engineer"),
                    "matching_skills": [],
                    "missing_skills": [],
                    "resume_improvements": [],
                    "likely_interview_questions": ["Q1"],
                    "evidence_backed_answers": [],
                    "technical_topics": [],
                    "company_specific_questions": [],
                    "star_answers": [],
                    "roadmap": [],
                }
            if name == "ResumeParser":
                update["resume_normalized"] = sample_resume
            if name == "JDParser":
                update["role_summary"] = "Backend Engineer"
                update["required_skills"] = [{"name": "Python"}]
            if name == "CompanyResearch":
                update["company_overview"] = "Acme overview"
                update["company_context"] = "context"
            if name == "SkillGapAnalysis":
                update["matching_skills"] = [{"name": "Python", "evidence": "Skills: Python"}]
                update["missing_skills"] = [{"name": "Kubernetes"}]
            if name == "QuestionGeneration":
                update["likely_interview_questions"] = [f"Q{i}" for i in range(1, 21)]
                update["company_specific_questions"] = ["Why Acme?"]
                update["behavioural_questions"] = ["Tell me about a time…"]
            if name == "AnswerGeneration":
                update["evidence_backed_answers"] = []
                update["star_answers"] = []
            return update

        return _node

    graph_mod = "app.agents.graph"
    with (
        patch(f"{graph_mod}.resume_parser", new=await passthrough("ResumeParser")),
        patch(f"{graph_mod}.jd_parser", new=await passthrough("JDParser")),
        patch(f"{graph_mod}.company_research", new=await passthrough("CompanyResearch")),
        patch(f"{graph_mod}.skill_gap_analysis", new=await passthrough("SkillGapAnalysis")),
        patch(f"{graph_mod}.question_generation", new=await passthrough("QuestionGeneration")),
        patch(f"{graph_mod}.answer_generation", new=await passthrough("AnswerGeneration")),
        patch(
            f"{graph_mod}.interview_preparation_report",
            new=await passthrough("InterviewPreparationReport"),
        ),
    ):
        graph = build_validated_brief_graph()
        initial: BriefState = {
            "session_id": str(uuid4()),
            "company_name": "Acme",
            "resume_text": sample_resume,
            "jd_text": sample_jd,
            "evidence_fallback": "No evidence found.",
            "error": None,
        }
        final = await graph.ainvoke(initial)
        assert final.get("error") in (None, "")
        assert final.get("report")
        assert final["current_step"] == "InterviewPreparationReport"


@pytest.mark.asyncio
async def test_validated_graph_stops_on_node_error():
    async def failing_resume(state: BriefState) -> BriefState:
        return {**state, "error": "resume missing", "current_step": "ResumeParser"}

    async def should_not_run(state: BriefState) -> BriefState:
        raise AssertionError("Downstream node should not run after error")

    with (
        patch("app.agents.graph.resume_parser", new=failing_resume),
        patch("app.agents.graph.jd_parser", new=should_not_run),
        patch("app.agents.graph.company_research", new=should_not_run),
        patch("app.agents.graph.skill_gap_analysis", new=should_not_run),
        patch("app.agents.graph.question_generation", new=should_not_run),
        patch("app.agents.graph.answer_generation", new=should_not_run),
        patch("app.agents.graph.interview_preparation_report", new=should_not_run),
    ):
        graph = build_validated_brief_graph()
        final = await graph.ainvoke(
            {
                "session_id": str(uuid4()),
                "company_name": "Acme",
                "resume_text": "x",
                "jd_text": "y",
            }
        )
        assert final.get("error") == "resume missing"
