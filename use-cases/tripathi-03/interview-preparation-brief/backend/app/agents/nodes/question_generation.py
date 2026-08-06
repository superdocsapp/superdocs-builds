"""Node: QuestionGeneration — categorized interview questions with metadata."""

from __future__ import annotations

from app.agents.base import BaseNode
from app.agents.contracts import QuestionGenerationInput, QuestionGenerationOutput
from app.agents.state import BriefState
from app.schemas.questions import InterviewQuestionRequest
from app.services.questions.generator import InterviewQuestionGenerator


class QuestionGeneration(BaseNode[QuestionGenerationInput, QuestionGenerationOutput]):
    name = "QuestionGeneration"
    input_model = QuestionGenerationInput
    output_model = QuestionGenerationOutput

    def __init__(self) -> None:
        self._last_bank_json: dict | None = None

    def build_input(self, state: BriefState) -> dict:
        return {
            "session_id": state.get("session_id", ""),
            "company_name": state.get("company_name", ""),
            "company_overview": state.get("company_overview", ""),
            "role_summary": state.get("role_summary", ""),
            "required_skills": state.get("required_skills") or [],
            "matching_skills": state.get("matching_skills") or [],
            "missing_skills": state.get("missing_skills") or [],
            "jd_text": state.get("jd_text", ""),
            "resume_normalized": state.get("resume_normalized") or state.get("resume_text", ""),
        }

    async def execute(
        self,
        node_input: QuestionGenerationInput,
        state: BriefState,
    ) -> QuestionGenerationOutput:
        company_data = state.get("company_profile") or node_input.company_overview or ""
        company_payload: str | dict = (
            company_data if isinstance(company_data, dict) else str(company_data)
        )

        response = await InterviewQuestionGenerator().generate(
            InterviewQuestionRequest(
                resume_text=node_input.resume_normalized,
                jd_text=node_input.jd_text,
                company_name=node_input.company_name,
                company_data=company_payload,
                role_summary=node_input.role_summary,
            )
        )
        self._last_bank_json = response.question_bank.model_dump()
        bank = response.question_bank

        likely = (
            [q.question for q in bank.technical_questions]
            + [q.question for q in bank.scenario_based_questions]
            + [q.question for q in bank.system_design_questions]
            + [q.question for q in bank.coding_questions]
        )
        seen: set[str] = set()
        likely_unique: list[str] = []
        for question in likely:
            if question not in seen:
                seen.add(question)
                likely_unique.append(question)

        while len(likely_unique) < 20:
            likely_unique.append(
                "Discuss how your experience prepares you for responsibility "
                f"#{len(likely_unique) + 1} in this role."
            )

        return QuestionGenerationOutput(
            likely_interview_questions=likely_unique[:20],
            company_specific_questions=[q.question for q in bank.company_specific_questions],
            behavioural_questions=[q.question for q in bank.behavioral_questions],
        )

    def merge_output(
        self,
        state: BriefState,
        node_output: QuestionGenerationOutput,
    ) -> BriefState:
        merged: BriefState = {
            **state,
            "likely_interview_questions": node_output.likely_interview_questions,
            "company_specific_questions": node_output.company_specific_questions,
            "behavioural_questions": node_output.behavioural_questions,
        }
        if self._last_bank_json:
            merged["question_bank"] = self._last_bank_json
        return merged


question_generation = QuestionGeneration()
