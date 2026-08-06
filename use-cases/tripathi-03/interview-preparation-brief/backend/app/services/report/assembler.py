"""Assemble a professional Interview Preparation Report from grounded inputs."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger
from app.schemas.brief import EvidenceAnswer, SkillItem
from app.schemas.questions import InterviewQuestionBank
from app.schemas.report import (
    CoverPage,
    InterviewPreparationReportDocument,
    MatchScore,
    ReportGenerateRequest,
    RevisionItem,
)

logger = get_logger(__name__)
REVISION_BASE = "https://revise.local/topic"


class ReportAssembler:
    """Build all report sections without inventing unsupported candidate facts."""

    def assemble(self, request: ReportGenerateRequest) -> InterviewPreparationReportDocument:
        matching = request.matching_skills
        missing = request.missing_skills
        required = request.required_skills or (matching + missing)

        match_score = self._compute_match_score(matching, missing, required)
        strengths = self._build_strengths(matching)
        weaknesses = self._build_weaknesses(missing, request.technical_topics)
        revision_plan = self._build_revision_plan(missing, request.technical_topics)
        recommendations = request.final_recommendations or self._build_recommendations(
            match_score,
            missing,
            request.resume_improvements,
        )

        question_bank: InterviewQuestionBank | dict
        if request.question_bank:
            try:
                question_bank = InterviewQuestionBank.model_validate(request.question_bank)
            except Exception:  # noqa: BLE001
                question_bank = request.question_bank
        else:
            question_bank = self._questions_from_flat_lists(request)

        behavioral_answers = [
            a
            for a in request.evidence_backed_answers
            if self._looks_behavioral(a.question)
        ]

        target_role = request.target_role or self._infer_role_title(request.role_summary)

        report = InterviewPreparationReportDocument(
            cover_page=CoverPage(
                title="Interview Preparation Report",
                candidate_name=request.candidate_name,
                company_name=request.company_name,
                target_role=target_role,
                prepared_on=datetime.now(timezone.utc),
            ),
            company_overview=request.company_overview or "Unknown",
            role_summary=request.role_summary or "Unknown",
            resume_match_score=match_score,
            strengths=strengths,
            weaknesses=weaknesses,
            skill_gap={
                "summary": request.gap_analysis_summary
                or f"{match_score.matching_count} matching · {match_score.missing_count} missing",
                "matching_skills": [s.model_dump() for s in matching],
                "missing_skills": [s.model_dump() for s in missing],
                "required_skills": [s.model_dump() for s in required],
            },
            resume_improvements=request.resume_improvements,
            interview_questions=question_bank,
            evidence_backed_answers=request.evidence_backed_answers,
            behavioral_answers=behavioral_answers,
            star_stories=request.star_answers,
            revision_plan=revision_plan,
            day_30_60_90_plan=request.roadmap or self._default_roadmap(missing),
            final_recommendations=recommendations,
            likely_interview_questions=request.likely_interview_questions,
            company_specific_questions=request.company_specific_questions,
            technical_topics=request.technical_topics,
            matching_skills=matching,
            missing_skills=missing,
            required_skills=required,
        )
        logger.info(
            "Assembled report company=%s score=%s strengths=%s weaknesses=%s",
            request.company_name,
            match_score.score,
            len(strengths),
            len(weaknesses),
        )
        return report

    def _compute_match_score(
        self,
        matching: list[SkillItem],
        missing: list[SkillItem],
        required: list[SkillItem],
    ) -> MatchScore:
        matching_count = len(matching)
        missing_count = len(missing)
        required_count = len(required) if required else matching_count + missing_count
        if required_count <= 0:
            score = 0
            summary = "Insufficient skill data to compute a match score."
        else:
            score = int(round((matching_count / required_count) * 100))
            score = max(0, min(100, score))
            summary = (
                f"Resume matches {matching_count} of {required_count} required skills "
                f"({score}%). {missing_count} skill gap(s) identified from the JD."
            )
        return MatchScore(
            score=score,
            matching_count=matching_count,
            missing_count=missing_count,
            required_count=required_count,
            summary=summary,
        )

    def _build_strengths(self, matching: list[SkillItem]) -> list[str]:
        strengths: list[str] = []
        for skill in matching:
            if skill.evidence:
                strengths.append(f"{skill.name} — supported by resume: “{skill.evidence}”")
            else:
                strengths.append(f"{skill.name} — listed as a matching skill against the JD")
        if not strengths:
            strengths.append(
                "No evidence-backed matching skills were identified from the resume vs JD comparison."
            )
        return strengths

    def _build_weaknesses(
        self,
        missing: list[SkillItem],
        technical_topics: list[str],
    ) -> list[str]:
        weaknesses = [f"Missing JD skill: {skill.name}" for skill in missing]
        for topic in technical_topics:
            line = f"Technical revision needed: {topic}"
            if line not in weaknesses:
                weaknesses.append(line)
        if not weaknesses:
            weaknesses.append("No explicit skill gaps were detected from the provided inputs.")
        return weaknesses

    def _build_revision_plan(
        self,
        missing: list[SkillItem],
        technical_topics: list[str],
    ) -> list[RevisionItem]:
        plan: list[RevisionItem] = []
        for skill in missing:
            slug = skill.name.lower().replace(" ", "-")
            plan.append(
                RevisionItem(
                    topic=skill.name,
                    reason="Required by JD and not evidenced in resume",
                    priority="High",
                    revision_link=f"{REVISION_BASE}/skills/{slug}",
                )
            )
        for topic in technical_topics:
            if any(p.topic.lower() == topic.lower() for p in plan):
                continue
            slug = topic.lower().replace(" ", "-")
            plan.append(
                RevisionItem(
                    topic=topic,
                    reason="Flagged as a technical topic to revise before interviews",
                    priority="Medium",
                    revision_link=f"{REVISION_BASE}/technical/{slug}",
                )
            )
        if not plan:
            plan.append(
                RevisionItem(
                    topic="Role fundamentals",
                    reason="Keep core JD themes fresh even when gaps are minimal",
                    priority="Low",
                    revision_link=f"{REVISION_BASE}/overview",
                )
            )
        return plan

    def _build_recommendations(
        self,
        match_score: MatchScore,
        missing: list[SkillItem],
        improvements: list[str],
    ) -> list[str]:
        recs = [
            f"Lead with evidenced strengths; current resume–JD match score is {match_score.score}%.",
            "Answer technical and behavioral questions using only resume-supported examples.",
            "If asked about a gap area, acknowledge it and describe a concrete learning plan — do not invent experience.",
        ]
        if missing:
            top = ", ".join(s.name for s in missing[:3])
            recs.append(f"Prioritize closing these gaps before the interview: {top}.")
        if improvements:
            recs.append(f"Update the resume with: {improvements[0]}")
        recs.append("Follow the 30-60-90 plan to structure preparation across the next weeks.")
        return recs

    def _questions_from_flat_lists(
        self,
        request: ReportGenerateRequest,
    ) -> dict:
        def wrap(questions: list[str]) -> list[dict]:
            return [
                {
                    "question": q,
                    "difficulty": "Medium",
                    "expected_answer": "No evidence found.",
                    "resume_evidence": "No evidence found.",
                    "missing_knowledge": [],
                    "revision_links": [
                        {
                            "title": "Revise topic",
                            "url": f"{REVISION_BASE}/overview",
                        }
                    ],
                }
                for q in questions
            ]

        return {
            "technical_questions": wrap(request.likely_interview_questions[:8]),
            "behavioral_questions": [],
            "company_specific_questions": wrap(request.company_specific_questions),
            "scenario_based_questions": [],
            "system_design_questions": [],
            "coding_questions": [],
        }

    def _default_roadmap(self, missing: list[SkillItem]) -> list:
        from app.schemas.brief import RoadmapPhase

        focus = ", ".join(s.name for s in missing[:3]) or "core JD competencies"
        return [
            RoadmapPhase(
                phase="30",
                goals=[f"Map resume stories to JD requirements", f"Begin revision on: {focus}"],
                actions=[
                    "Draft STAR outlines for top behavioral themes",
                    "Review company overview and product notes daily",
                ],
            ),
            RoadmapPhase(
                phase="60",
                goals=["Deepen technical revision", "Practice mock interviews"],
                actions=[
                    "Complete coding/system-design drills for gap areas",
                    "Refine resume bullets with quantified, evidenced impact",
                ],
            ),
            RoadmapPhase(
                phase="90",
                goals=["Polish delivery", "Finalize interview logistics"],
                actions=[
                    "Run full mock loops with timed answers",
                    "Prepare thoughtful questions for the interviewer",
                ],
            ),
        ]

    @staticmethod
    def _looks_behavioral(question: str) -> bool:
        q = question.lower()
        return any(
            phrase in q
            for phrase in (
                "tell me about a time",
                "describe a time",
                "give an example",
                "how did you handle",
                "conflict",
                "feedback",
                " mentored",
            )
        )

    @staticmethod
    def _infer_role_title(role_summary: str) -> str | None:
        if not role_summary:
            return None
        first = role_summary.strip().split("\n")[0].strip()
        return first[:120] if first else None
