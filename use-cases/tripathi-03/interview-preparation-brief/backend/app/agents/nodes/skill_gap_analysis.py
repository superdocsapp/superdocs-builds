"""Node: SkillGapAnalysis — matching/missing skills without fabrication."""

from __future__ import annotations

from app.agents.base import BaseNode
from app.agents.contracts import SkillGapAnalysisInput, SkillGapAnalysisOutput
from app.agents.llm import invoke_structured
from app.agents.prompts.templates import NO_EVIDENCE, SKILL_GAP_SYSTEM
from app.agents.state import BriefState
from app.schemas.agent import SkillMatchOutput
from app.schemas.brief import SkillItem


class SkillGapAnalysis(BaseNode[SkillGapAnalysisInput, SkillGapAnalysisOutput]):
    name = "SkillGapAnalysis"
    input_model = SkillGapAnalysisInput
    output_model = SkillGapAnalysisOutput

    def build_input(self, state: BriefState) -> dict:
        return {
            "session_id": state.get("session_id", ""),
            "resume_normalized": state.get("resume_normalized") or state.get("resume_text", ""),
            "jd_text": state.get("jd_text", ""),
            "role_summary": state.get("role_summary", ""),
            "required_skills": state.get("required_skills") or [],
        }

    async def execute(
        self,
        node_input: SkillGapAnalysisInput,
        state: BriefState,
    ) -> SkillGapAnalysisOutput:
        result = await invoke_structured(
            schema=SkillMatchOutput,
            system=SKILL_GAP_SYSTEM,
            user=(
                "Perform resume vs JD skill gap analysis.\n"
                "Rules:\n"
                "- matching_skills must include short evidence quotes from the resume\n"
                f"- if no evidence exists for a skill, put it in missing_skills (do not invent)\n"
                f"- never fabricate employers, tools, or metrics\n"
                f"- if you cannot quote evidence, use exactly: {NO_EVIDENCE}\n\n"
                f"Required skills JSON:\n{[s.model_dump() for s in node_input.required_skills]}\n\n"
                f"Role summary:\n{node_input.role_summary}\n\n"
                f"Resume:\n{node_input.resume_normalized[:20000]}\n\n"
                f"Job description:\n{node_input.jd_text[:12000]}"
            ),
        )

        matching: list[SkillItem] = []
        for skill in result.matching_skills:
            evidence = (skill.evidence or "").strip()
            if not evidence or evidence == NO_EVIDENCE:
                # Demote unsupported "matches" instead of fabricating.
                continue
            matching.append(skill)

        return SkillGapAnalysisOutput(
            matching_skills=matching,
            missing_skills=result.missing_skills,
            gap_analysis_summary=result.gap_analysis_summary,
            resume_improvements=result.resume_improvements,
            technical_topics=result.technical_topics,
        )

    def merge_output(
        self,
        state: BriefState,
        node_output: SkillGapAnalysisOutput,
    ) -> BriefState:
        return {
            **state,
            "matching_skills": [s.model_dump() for s in node_output.matching_skills],
            "missing_skills": [s.model_dump() for s in node_output.missing_skills],
            "gap_analysis_summary": node_output.gap_analysis_summary,
            "resume_improvements": node_output.resume_improvements,
            "technical_topics": node_output.technical_topics,
        }


skill_gap_analysis = SkillGapAnalysis()
