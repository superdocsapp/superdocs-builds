"""Node: ResumeParser — validate and normalize resume text in shared state."""

from __future__ import annotations

import re

from app.agents.base import BaseNode
from app.agents.contracts import ResumeParserInput, ResumeParserOutput
from app.agents.state import BriefState


class ResumeParser(BaseNode[ResumeParserInput, ResumeParserOutput]):
    name = "ResumeParser"
    input_model = ResumeParserInput
    output_model = ResumeParserOutput

    def build_input(self, state: BriefState) -> dict:
        return {
            "session_id": state.get("session_id", ""),
            "resume_text": state.get("resume_text", ""),
        }

    async def execute(
        self,
        node_input: ResumeParserInput,
        state: BriefState,
    ) -> ResumeParserOutput:
        # Normalize whitespace only — never invent resume content.
        normalized = re.sub(r"[ \t]+", " ", node_input.resume_text)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        return ResumeParserOutput(
            resume_normalized=normalized,
            resume_char_count=len(normalized),
        )

    def merge_output(
        self,
        state: BriefState,
        node_output: ResumeParserOutput,
    ) -> BriefState:
        return {
            **state,
            "resume_normalized": node_output.resume_normalized,
            "resume_text": node_output.resume_normalized,
            "resume_char_count": node_output.resume_char_count,
        }


resume_parser = ResumeParser()
