"""LangGraph workflow builder.

ResumeParser → JDParser → CompanyResearch → SkillGapAnalysis
→ QuestionGeneration → AnswerGeneration → InterviewPreparationReport
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.base import NodeValidationError
from app.agents.nodes.answer_generation import answer_generation
from app.agents.nodes.company_research import company_research
from app.agents.nodes.interview_preparation_report import interview_preparation_report
from app.agents.nodes.jd_parser import jd_parser
from app.agents.nodes.question_generation import question_generation
from app.agents.nodes.resume_parser import resume_parser
from app.agents.nodes.skill_gap_analysis import skill_gap_analysis
from app.agents.state import BriefState
from app.core.logging import get_logger

logger = get_logger(__name__)

NODE_ORDER = [
    "ResumeParser",
    "JDParser",
    "CompanyResearch",
    "SkillGapAnalysis",
    "QuestionGeneration",
    "AnswerGeneration",
    "InterviewPreparationReport",
]


async def _safe_node(node_callable, state: BriefState) -> BriefState:
    """Wrap node execution so validation errors become structured state errors."""
    try:
        return await node_callable(state)
    except NodeValidationError as exc:
        logger.error("Node validation failure: %s", exc)
        return {
            **state,
            "error": str(exc),
            "current_step": state.get("current_step") or "validation_error",
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Node execution failure: %s", exc)
        return {
            **state,
            "error": str(exc),
            "current_step": state.get("current_step") or "execution_error",
        }


def build_brief_graph():
    graph = StateGraph(BriefState)

    graph.add_node("ResumeParser", resume_parser)
    graph.add_node("JDParser", jd_parser)
    graph.add_node("CompanyResearch", company_research)
    graph.add_node("SkillGapAnalysis", skill_gap_analysis)
    graph.add_node("QuestionGeneration", question_generation)
    graph.add_node("AnswerGeneration", answer_generation)
    graph.add_node("InterviewPreparationReport", interview_preparation_report)

    graph.add_edge(START, "ResumeParser")
    graph.add_edge("ResumeParser", "JDParser")
    graph.add_edge("JDParser", "CompanyResearch")
    graph.add_edge("CompanyResearch", "SkillGapAnalysis")
    graph.add_edge("SkillGapAnalysis", "QuestionGeneration")
    graph.add_edge("QuestionGeneration", "AnswerGeneration")
    graph.add_edge("AnswerGeneration", "InterviewPreparationReport")
    graph.add_edge("InterviewPreparationReport", END)

    compiled = graph.compile()
    logger.info("Compiled LangGraph workflow: %s", " → ".join(NODE_ORDER))
    return compiled


def build_validated_brief_graph():
    """Same workflow with validation/error wrapping around each node."""
    graph = StateGraph(BriefState)

    async def resume_parser_node(state: BriefState) -> BriefState:
        return await _safe_node(resume_parser, state)

    async def jd_parser_node(state: BriefState) -> BriefState:
        return await _safe_node(jd_parser, state)

    async def company_research_node(state: BriefState) -> BriefState:
        return await _safe_node(company_research, state)

    async def skill_gap_node(state: BriefState) -> BriefState:
        return await _safe_node(skill_gap_analysis, state)

    async def question_node(state: BriefState) -> BriefState:
        return await _safe_node(question_generation, state)

    async def answer_node(state: BriefState) -> BriefState:
        return await _safe_node(answer_generation, state)

    async def report_node(state: BriefState) -> BriefState:
        return await _safe_node(interview_preparation_report, state)

    graph.add_node("ResumeParser", resume_parser_node)
    graph.add_node("JDParser", jd_parser_node)
    graph.add_node("CompanyResearch", company_research_node)
    graph.add_node("SkillGapAnalysis", skill_gap_node)
    graph.add_node("QuestionGeneration", question_node)
    graph.add_node("AnswerGeneration", answer_node)
    graph.add_node("InterviewPreparationReport", report_node)

    def _route_after(state: BriefState) -> str:
        return "error" if state.get("error") else "continue"

    graph.add_edge(START, "ResumeParser")
    for src, dest in [
        ("ResumeParser", "JDParser"),
        ("JDParser", "CompanyResearch"),
        ("CompanyResearch", "SkillGapAnalysis"),
        ("SkillGapAnalysis", "QuestionGeneration"),
        ("QuestionGeneration", "AnswerGeneration"),
        ("AnswerGeneration", "InterviewPreparationReport"),
    ]:
        graph.add_conditional_edges(
            src,
            _route_after,
            {"continue": dest, "error": END},
        )
    graph.add_edge("InterviewPreparationReport", END)

    compiled = graph.compile()
    logger.info("Compiled validated LangGraph workflow with early-stop on errors")
    return compiled
