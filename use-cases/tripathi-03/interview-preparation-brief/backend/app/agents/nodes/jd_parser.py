"""Node: JDParser — role summary + required skills from JD text."""

from __future__ import annotations

from app.agents.base import BaseNode
from app.agents.contracts import JDParserInput, JDParserOutput
from app.agents.llm import invoke_structured
from app.agents.prompts.templates import JD_PARSER_SYSTEM
from app.agents.state import BriefState
from app.schemas.agent import RoleSummaryOutput


class JDParser(BaseNode[JDParserInput, JDParserOutput]):
    name = "JDParser"
    input_model = JDParserInput
    output_model = JDParserOutput

    def build_input(self, state: BriefState) -> dict:
        return {
            "session_id": state.get("session_id", ""),
            "jd_text": state.get("jd_text", ""),
        }

    async def execute(
        self,
        node_input: JDParserInput,
        state: BriefState,
    ) -> JDParserOutput:
        result = await invoke_structured(
            schema=RoleSummaryOutput,
            system=JD_PARSER_SYSTEM,
            user=(
                "Extract a concise role summary and required skills from this job description.\n"
                "Only include skills explicitly stated or clearly implied by the JD.\n"
                "Return JSON like:\n"
                '{"role_summary":"...","required_skills":[{"name":"Python","evidence":"JD mentions Python"}]}\n\n'
                f"{node_input.jd_text[:20000]}"
            ),
        )
        return JDParserOutput(
            role_summary=result.role_summary.strip(),
            required_skills=result.required_skills,
        )

    def merge_output(self, state: BriefState, node_output: JDParserOutput) -> BriefState:
        return {
            **state,
            "role_summary": node_output.role_summary,
            "required_skills": [s.model_dump() for s in node_output.required_skills],
        }


jd_parser = JDParser()
