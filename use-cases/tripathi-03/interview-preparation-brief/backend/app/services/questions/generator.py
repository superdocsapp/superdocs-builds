"""Interview question generator service.

Inputs: resume, JD, company data.
Outputs categorized questions with difficulty, expected answer,
resume evidence, missing knowledge, and revision link placeholders.

Never fabricates resume evidence. Unsupported evidence → "No evidence found."
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.llm import invoke_structured
from app.core.logging import get_logger
from app.schemas.questions import (
    NO_EVIDENCE,
    REVISION_PLACEHOLDER_BASE,
    Difficulty,
    InterviewQuestionBank,
    InterviewQuestionItem,
    InterviewQuestionRequest,
    InterviewQuestionResponse,
    QuestionCategoryLLMOutput,
    RevisionLink,
)

logger = get_logger(__name__)

CATEGORY_SPECS: list[tuple[str, str, int]] = [
    ("technical", "technical interview questions about tools/skills from the JD/resume", 3),
    ("behavioral", "behavioral STAR-style questions", 3),
    ("company", "company-specific preparation questions", 2),
    ("scenario", "scenario-based workplace questions", 2),
    ("system-design", "system design questions relevant to the role", 2),
    ("coding", "coding/problem-solving questions relevant to the role", 2),
]

SYSTEM_PROMPT = f"""You generate interview questions for a specific candidate and role.

Rules:
1. Use ONLY the provided Resume, JD, and Company Data.
2. Do NOT invent resume experience, employers, metrics, or technologies.
3. For each question provide:
   - question
   - difficulty: Easy | Medium | Hard
   - expected_answer (1-2 short sentences, conceptual if no resume evidence)
   - resume_evidence: exact resume span OR exactly "{NO_EVIDENCE}"
   - missing_knowledge: short topic strings
   - revision_links: use ONLY placeholder urls like "{REVISION_PLACEHOLDER_BASE}/topic-name"
4. Keep JSON compact. No markdown. No Wikipedia URLs. No parentheses in URLs.
5. Return object shape: {{"questions":[...only this category...]}}
"""


class InterviewQuestionGenerator:
    async def generate(
        self,
        request: InterviewQuestionRequest,
    ) -> InterviewQuestionResponse:
        company_block = self._format_company_data(request.company_data)
        shared_context = (
            f"Company name: {request.company_name}\n"
            f"Role summary: {request.role_summary or 'N/A'}\n\n"
            f"COMPANY DATA:\n{company_block[:4000]}\n\n"
            f"JOB DESCRIPTION:\n{request.jd_text[:8000]}\n\n"
            f"RESUME:\n{request.resume_text[:10000]}"
        )

        buckets: dict[str, list[InterviewQuestionItem]] = {
            "technical": [],
            "behavioral": [],
            "company": [],
            "scenario": [],
            "system-design": [],
            "coding": [],
        }

        for slug, description, count in CATEGORY_SPECS:
            try:
                result = await invoke_structured(
                    schema=QuestionCategoryLLMOutput,
                    system=SYSTEM_PROMPT,
                    user=(
                        f"Generate exactly {count} {description}.\n"
                        "Return JSON with key questions only. Example item fields: "
                        "question, difficulty, expected_answer, resume_evidence, "
                        "missing_knowledge, revision_links.\n"
                        f"Use resume_evidence '{NO_EVIDENCE}' when unsupported.\n"
                        f"Use revision url base {REVISION_PLACEHOLDER_BASE}/topic-name only.\n\n"
                        f"{shared_context}"
                    ),
                )
                buckets[slug] = self._normalize_items(
                    result.questions,
                    request.resume_text,
                    slug,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Category %s generation failed (%s); using fallbacks", slug, exc)
                buckets[slug] = []

        bank = InterviewQuestionBank(
            technical_questions=buckets["technical"],
            behavioral_questions=buckets["behavioral"],
            company_specific_questions=buckets["company"],
            scenario_based_questions=buckets["scenario"],
            system_design_questions=buckets["system-design"],
            coding_questions=buckets["coding"],
        )
        bank = self._ensure_minimums(bank, request)

        totals = {
            "technical_questions": len(bank.technical_questions),
            "behavioral_questions": len(bank.behavioral_questions),
            "company_specific_questions": len(bank.company_specific_questions),
            "scenario_based_questions": len(bank.scenario_based_questions),
            "system_design_questions": len(bank.system_design_questions),
            "coding_questions": len(bank.coding_questions),
            "all": (
                len(bank.technical_questions)
                + len(bank.behavioral_questions)
                + len(bank.company_specific_questions)
                + len(bank.scenario_based_questions)
                + len(bank.system_design_questions)
                + len(bank.coding_questions)
            ),
        }
        logger.info(
            "Generated interview questions company=%s total=%s",
            request.company_name,
            totals["all"],
        )
        return InterviewQuestionResponse(
            company_name=request.company_name,
            question_bank=bank,
            totals=totals,
        )

    def _normalize_items(
        self,
        items: list[InterviewQuestionItem],
        resume_text: str,
        category_slug: str,
    ) -> list[InterviewQuestionItem]:
        normalized: list[InterviewQuestionItem] = []
        for index, item in enumerate(items):
            evidence = self._ground_evidence(item.resume_evidence, resume_text)
            missing = [m.strip() for m in item.missing_knowledge if m and m.strip()]
            links = item.revision_links or []
            # Force placeholder links — avoid fragile external URLs from the model
            if missing:
                links = [
                    RevisionLink(
                        title=f"Revise: {topic}",
                        url=f"{REVISION_PLACEHOLDER_BASE}/{category_slug}/{self._slugify(topic)}",
                    )
                    for topic in missing[:3]
                ]
            elif not links:
                links = [
                    RevisionLink(
                        title=f"Revise: {category_slug.replace('-', ' ').title()}",
                        url=f"{REVISION_PLACEHOLDER_BASE}/{category_slug}/overview",
                    )
                ]
            else:
                # Rewrite any model URLs to placeholders
                links = [
                    RevisionLink(
                        title=link.title or "Revise topic",
                        url=f"{REVISION_PLACEHOLDER_BASE}/{category_slug}/{self._slugify(link.title or 'topic')}",
                    )
                    for link in links[:3]
                ]

            expected = (item.expected_answer or "").strip() or NO_EVIDENCE
            if evidence == NO_EVIDENCE and "resume" in expected.lower() and "worked at" in expected.lower():
                expected = (
                    "No resume evidence available. Prepare a structured answer covering "
                    "approach, trade-offs, and validation steps relevant to this question."
                )

            normalized.append(
                InterviewQuestionItem(
                    question=item.question.strip(),
                    difficulty=item.difficulty or Difficulty.MEDIUM,
                    expected_answer=expected,
                    resume_evidence=evidence,
                    missing_knowledge=missing,
                    revision_links=links,
                )
            )
            if index >= 4:
                break
        return normalized

    def _ground_evidence(self, evidence: str | None, resume_text: str) -> str:
        if not evidence or not evidence.strip():
            return NO_EVIDENCE
        span = evidence.strip()
        if span in {NO_EVIDENCE, "Unknown", "N/A", "None"}:
            return NO_EVIDENCE
        if span in resume_text:
            return span
        norm_span = " ".join(span.split()).lower()
        norm_resume = " ".join(resume_text.split()).lower()
        if norm_span and norm_span in norm_resume:
            return span
        return NO_EVIDENCE

    def _ensure_minimums(
        self,
        bank: InterviewQuestionBank,
        request: InterviewQuestionRequest,
    ) -> InterviewQuestionBank:
        def fill(
            current: list[InterviewQuestionItem],
            templates: list[str],
            category: str,
            difficulty: Difficulty,
        ) -> list[InterviewQuestionItem]:
            items = list(current)
            for template in templates:
                if len(items) >= 2:
                    break
                if any(i.question == template for i in items):
                    continue
                items.append(
                    InterviewQuestionItem(
                        question=template,
                        difficulty=difficulty,
                        expected_answer=(
                            "No resume evidence available. Outline a clear, structured response "
                            "tied to the JD requirements."
                        ),
                        resume_evidence=NO_EVIDENCE,
                        missing_knowledge=["Role-specific depth for this prompt"],
                        revision_links=[
                            RevisionLink(
                                title=f"Revise: {category}",
                                url=f"{REVISION_PLACEHOLDER_BASE}/{self._slugify(category)}/overview",
                            )
                        ],
                    )
                )
            return items

        company = request.company_name
        bank.technical_questions = fill(
            bank.technical_questions,
            [
                f"How would you apply your strongest technical skill to problems at {company}?",
                "Walk through a system you built and the trade-offs you made.",
                "Which part of our stack would require the most ramp-up for you, and why?",
            ],
            "technical",
            Difficulty.MEDIUM,
        )
        bank.behavioral_questions = fill(
            bank.behavioral_questions,
            [
                "Tell me about a time you resolved ambiguity with stakeholders.",
                "Describe a conflict on a team and how you handled it.",
                "Give an example of receiving hard feedback and what changed afterward.",
            ],
            "behavioral",
            Difficulty.MEDIUM,
        )
        bank.company_specific_questions = fill(
            bank.company_specific_questions,
            [
                f"Why {company}, and how does this role fit your trajectory?",
                f"What risks do you see for {company}'s product in the next year?",
            ],
            "company",
            Difficulty.MEDIUM,
        )
        bank.scenario_based_questions = fill(
            bank.scenario_based_questions,
            [
                "Production is degraded and metrics disagree — how do you triage?",
                "A stakeholder wants a shortcut that risks quality — what do you do?",
            ],
            "scenario",
            Difficulty.HARD,
        )
        bank.system_design_questions = fill(
            bank.system_design_questions,
            [
                "Design a service that ingests documents and serves ranked search results.",
                "How would you design rate limiting for a multi-tenant API?",
            ],
            "system-design",
            Difficulty.HARD,
        )
        bank.coding_questions = fill(
            bank.coding_questions,
            [
                "Implement an in-memory LRU cache and explain complexity.",
                "Given overlapping intervals, merge them efficiently.",
            ],
            "coding",
            Difficulty.MEDIUM,
        )
        return bank

    def _format_company_data(self, company_data: str | dict[str, Any]) -> str:
        if isinstance(company_data, dict):
            return json.dumps(company_data, indent=2, default=str)
        return str(company_data or "").strip() or "Unknown"

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return slug or "topic"
