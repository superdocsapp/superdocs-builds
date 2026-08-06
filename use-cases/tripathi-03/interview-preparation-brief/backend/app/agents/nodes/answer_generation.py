"""Node: AnswerGeneration — resume-evidence answers only; never fabricate."""

from __future__ import annotations

from uuid import UUID

from app.agents.base import BaseNode
from app.agents.contracts import (
    NO_EVIDENCE,
    AnswerGenerationInput,
    AnswerGenerationOutput,
)
from app.agents.llm import invoke_structured, invoke_text
from app.agents.prompts.templates import ANSWER_GENERATION_SYSTEM
from app.agents.state import BriefState
from app.database.session import AsyncSessionLocal
from app.schemas.brief import EvidenceAnswer, StarAnswer
from app.services.rag.retriever import Retriever
from app.utils.evidence_guard import enforce_evidence_or_fallback


class AnswerGeneration(BaseNode[AnswerGenerationInput, AnswerGenerationOutput]):
    name = "AnswerGeneration"
    input_model = AnswerGenerationInput
    output_model = AnswerGenerationOutput

    def build_input(self, state: BriefState) -> dict:
        return {
            "session_id": state.get("session_id", ""),
            "likely_interview_questions": state.get("likely_interview_questions") or [],
            "behavioural_questions": state.get("behavioural_questions") or [],
            "evidence_fallback": state.get("evidence_fallback") or NO_EVIDENCE,
        }

    async def execute(
        self,
        node_input: AnswerGenerationInput,
        state: BriefState,
    ) -> AnswerGenerationOutput:
        fallback = node_input.evidence_fallback or NO_EVIDENCE
        session_id = UUID(node_input.session_id)
        questions = node_input.likely_interview_questions[:8]
        behavioural = (node_input.behavioural_questions or [
            "Tell me about a time you solved a difficult technical problem.",
            "Describe a situation where you had to collaborate under pressure.",
            "Give an example of how you handled ambiguous requirements.",
            "Tell me about a time you improved a process or system.",
        ])[:3]

        evidence_answers: list[EvidenceAnswer] = []
        star_answers: list[StarAnswer] = []

        async with AsyncSessionLocal() as db:
            retriever = Retriever(db)

            for question in questions:
                spans = await retriever.retrieve_resume_evidence(
                    session_id=session_id,
                    query=question,
                    top_k=4,
                )
                if not spans:
                    evidence_answers.append(
                        EvidenceAnswer(
                            question=question,
                            answer=fallback,
                            evidence_spans=[],
                            has_evidence=False,
                        )
                    )
                    continue

                evidence_block = "\n---\n".join(spans)
                raw = await invoke_text(
                    system=ANSWER_GENERATION_SYSTEM,
                    user=(
                        f"Question: {question}\n\n"
                        f"Resume evidence:\n{evidence_block}\n\n"
                        "Write a concise interview answer using only the evidence. "
                        f"If insufficient, reply exactly: {fallback}"
                    ),
                )
                answer, has_evidence = enforce_evidence_or_fallback(raw, spans)
                evidence_answers.append(
                    EvidenceAnswer(
                        question=question,
                        answer=answer,
                        evidence_spans=spans if has_evidence else [],
                        has_evidence=has_evidence,
                    )
                )

            for question in behavioural:
                spans = await retriever.retrieve_resume_evidence(
                    session_id=session_id,
                    query=question,
                    top_k=5,
                )
                if not spans:
                    star_answers.append(
                        StarAnswer(
                            question=question,
                            has_evidence=False,
                            note=fallback,
                            situation="",
                            task="",
                            action="",
                            result="",
                        )
                    )
                    continue

                evidence_block = "\n---\n".join(spans)
                star = await invoke_structured(
                    schema=StarAnswer,
                    system=ANSWER_GENERATION_SYSTEM,
                    user=(
                        "Build a STAR answer using ONLY the resume evidence.\n"
                        f"If evidence is insufficient, set has_evidence=false and "
                        f"note='{fallback}'. Leave STAR fields empty when unsupported.\n"
                        f"Question: {question}\n\nEvidence:\n{evidence_block}"
                    ),
                )

                if not star.has_evidence or not any(
                    [star.situation, star.task, star.action, star.result]
                ):
                    star_answers.append(
                        StarAnswer(
                            question=question,
                            has_evidence=False,
                            note=fallback,
                        )
                    )
                else:
                    star_answers.append(
                        StarAnswer(
                            question=question,
                            situation=star.situation,
                            task=star.task,
                            action=star.action,
                            result=star.result,
                            has_evidence=True,
                            note=None,
                        )
                    )

        return AnswerGenerationOutput(
            evidence_backed_answers=evidence_answers,
            star_answers=star_answers,
        )

    def merge_output(
        self,
        state: BriefState,
        node_output: AnswerGenerationOutput,
    ) -> BriefState:
        return {
            **state,
            "evidence_backed_answers": [
                a.model_dump() for a in node_output.evidence_backed_answers
            ],
            "star_answers": [a.model_dump() for a in node_output.star_answers],
        }


answer_generation = AnswerGeneration()
