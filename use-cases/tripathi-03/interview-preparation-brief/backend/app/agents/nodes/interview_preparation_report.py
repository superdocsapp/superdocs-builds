"""Node: InterviewPreparationReport — professional multi-section report."""

from __future__ import annotations

from app.agents.base import BaseNode
from app.agents.contracts import (
    InterviewPreparationReportInput,
    InterviewPreparationReportOutput,
)
from app.agents.llm import invoke_structured
from app.agents.prompts.templates import REPORT_SYSTEM
from app.agents.state import BriefState
from app.schemas.agent import ReportExtrasOutput
from app.schemas.report import ReportGenerateRequest
from app.services.report.assembler import ReportAssembler


class InterviewPreparationReport(
    BaseNode[InterviewPreparationReportInput, InterviewPreparationReportOutput]
):
    name = "InterviewPreparationReport"
    input_model = InterviewPreparationReportInput
    output_model = InterviewPreparationReportOutput

    def build_input(self, state: BriefState) -> dict:
        return {
            "session_id": state.get("session_id", ""),
            "company_name": state.get("company_name", ""),
            "company_overview": state.get("company_overview", ""),
            "role_summary": state.get("role_summary", ""),
            "required_skills": state.get("required_skills") or [],
            "matching_skills": state.get("matching_skills") or [],
            "missing_skills": state.get("missing_skills") or [],
            "gap_analysis_summary": state.get("gap_analysis_summary", ""),
            "resume_improvements": state.get("resume_improvements") or [],
            "technical_topics": state.get("technical_topics") or [],
            "likely_interview_questions": state.get("likely_interview_questions") or [],
            "company_specific_questions": state.get("company_specific_questions") or [],
            "evidence_backed_answers": state.get("evidence_backed_answers") or [],
            "star_answers": state.get("star_answers") or [],
        }

    async def execute(
        self,
        node_input: InterviewPreparationReportInput,
        state: BriefState,
    ) -> InterviewPreparationReportOutput:
        extras = await invoke_structured(
            schema=ReportExtrasOutput,
            system=REPORT_SYSTEM,
            user=(
                "Create a practical 30-60-90 day interview preparation roadmap.\n"
                "Use only the provided grounded context. Each phase needs goals and actions.\n"
                "Do not invent candidate achievements.\n\n"
                f"Company: {node_input.company_name}\n"
                f"Role summary: {node_input.role_summary}\n"
                f"Missing skills: {[s.model_dump() for s in node_input.missing_skills]}\n"
                f"Technical topics: {node_input.technical_topics}\n"
                f"Gap summary: {node_input.gap_analysis_summary}"
            ),
        )

        request = ReportGenerateRequest(
            company_name=node_input.company_name,
            company_overview=node_input.company_overview,
            role_summary=node_input.role_summary,
            required_skills=node_input.required_skills,
            matching_skills=node_input.matching_skills,
            missing_skills=node_input.missing_skills,
            gap_analysis_summary=node_input.gap_analysis_summary,
            resume_improvements=node_input.resume_improvements,
            technical_topics=node_input.technical_topics,
            likely_interview_questions=node_input.likely_interview_questions,
            company_specific_questions=node_input.company_specific_questions,
            evidence_backed_answers=node_input.evidence_backed_answers,
            star_answers=node_input.star_answers,
            roadmap=extras.roadmap,
            question_bank=state.get("question_bank"),
        )
        professional = ReportAssembler().assemble(request)
        payload = professional.model_dump(mode="json")
        # Keep legacy brief UI keys
        payload["roadmap"] = [p.model_dump() for p in professional.day_30_60_90_plan]
        payload["gap_analysis"] = {
            "matching_skills": payload.get("matching_skills") or [],
            "missing_skills": payload.get("missing_skills") or [],
            "summary": professional.resume_match_score.summary,
        }

        return InterviewPreparationReportOutput(
            roadmap=extras.roadmap,
            report=payload,
        )

    def merge_output(
        self,
        state: BriefState,
        node_output: InterviewPreparationReportOutput,
    ) -> BriefState:
        return {
            **state,
            "roadmap": [phase.model_dump() for phase in node_output.roadmap],
            "report": node_output.report,
        }


interview_preparation_report = InterviewPreparationReport()
