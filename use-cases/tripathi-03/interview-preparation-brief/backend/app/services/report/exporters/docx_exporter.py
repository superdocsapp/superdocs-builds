"""DOCX export for Interview Preparation Report."""

from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from app.schemas.report import InterviewPreparationReportDocument
from app.services.report.exporters.common import iter_question_groups, question_fields


def to_docx_bytes(report: InterviewPreparationReportDocument) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    cover = report.cover_page
    title = doc.add_heading(cover.title, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(
        f"{cover.company_name}  ·  {cover.target_role or 'Role TBD'}  ·  "
        f"{cover.candidate_name or 'Candidate'}  ·  "
        f"{cover.prepared_on.strftime('%Y-%m-%d')}"
    )
    tag = doc.add_paragraph(cover.tagline)
    tag.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tag.runs[0].italic = True
    tag.runs[0].font.color.rgb = RGBColor(0x5B, 0x6B, 0x7C)

    def h(text: str) -> None:
        doc.add_heading(text, level=1)

    def bullets(items: list[str]) -> None:
        if not items:
            doc.add_paragraph("—")
            return
        for item in items:
            doc.add_paragraph(item, style="List Bullet")

    h("Company Overview")
    doc.add_paragraph(report.company_overview or "—")

    h("Role Summary")
    doc.add_paragraph(report.role_summary or "—")

    h("Resume Match Score")
    doc.add_paragraph(f"Score: {report.resume_match_score.score}/100")
    doc.add_paragraph(report.resume_match_score.summary)

    h("Strengths")
    bullets(report.strengths)

    h("Weaknesses")
    bullets(report.weaknesses)

    h("Skill Gap")
    gap = report.skill_gap or {}
    doc.add_paragraph(gap.get("summary") or "—")
    doc.add_heading("Matching Skills", level=2)
    for skill in gap.get("matching_skills") or []:
        name = skill.get("name") if isinstance(skill, dict) else getattr(skill, "name", "")
        evidence = skill.get("evidence") if isinstance(skill, dict) else getattr(skill, "evidence", None)
        doc.add_paragraph(
            f"{name}" + (f" — {evidence}" if evidence else ""),
            style="List Bullet",
        )
    doc.add_heading("Missing Skills", level=2)
    for skill in gap.get("missing_skills") or []:
        name = skill.get("name") if isinstance(skill, dict) else getattr(skill, "name", "")
        doc.add_paragraph(name, style="List Bullet")

    h("Resume Improvements")
    bullets(report.resume_improvements or ["—"])

    h("Interview Questions")
    for title_text, items in iter_question_groups(report):
        doc.add_heading(title_text, level=2)
        for idx, raw in enumerate(items, start=1):
            q = question_fields(raw)
            doc.add_heading(f"Q{idx}. {q['question']}", level=3)
            doc.add_paragraph(f"Difficulty: {q['difficulty']}")
            doc.add_paragraph(f"Expected Answer: {q['expected_answer']}")
            doc.add_paragraph(f"Resume Evidence: {q['resume_evidence']}")
            doc.add_paragraph(
                "Missing Knowledge: " + (", ".join(q["missing_knowledge"]) or "—")
            )
            for link in q["revision_links"]:
                if isinstance(link, dict):
                    doc.add_paragraph(
                        f"Revision: {link.get('title')} ({link.get('url')})",
                        style="List Bullet",
                    )
                else:
                    doc.add_paragraph(
                        f"Revision: {getattr(link, 'title', '')} ({getattr(link, 'url', '')})",
                        style="List Bullet",
                    )

    h("Evidence-backed Answers")
    for idx, ans in enumerate(report.evidence_backed_answers, start=1):
        doc.add_heading(f"{idx}. {ans.question}", level=2)
        doc.add_paragraph(ans.answer)
        for span in ans.evidence_spans:
            doc.add_paragraph(span, style="List Bullet")

    h("Behavioral Answers")
    if not report.behavioral_answers:
        doc.add_paragraph("—")
    for idx, ans in enumerate(report.behavioral_answers, start=1):
        doc.add_heading(f"{idx}. {ans.question}", level=2)
        doc.add_paragraph(ans.answer)

    h("STAR Stories")
    for idx, star in enumerate(report.star_stories, start=1):
        doc.add_heading(f"{idx}. {star.question}", level=2)
        if not star.has_evidence:
            doc.add_paragraph(star.note or "No evidence found.")
        else:
            doc.add_paragraph(f"Situation: {star.situation}")
            doc.add_paragraph(f"Task: {star.task}")
            doc.add_paragraph(f"Action: {star.action}")
            doc.add_paragraph(f"Result: {star.result}")

    h("Revision Plan")
    for item in report.revision_plan:
        doc.add_paragraph(
            f"{item.topic} ({item.priority}) — {item.reason} [{item.revision_link}]",
            style="List Bullet",
        )

    h("30-60-90 Day Plan")
    for phase in report.day_30_60_90_plan:
        doc.add_heading(f"Day {phase.phase}", level=2)
        doc.add_paragraph("Goals")
        bullets(phase.goals)
        doc.add_paragraph("Actions")
        bullets(phase.actions)

    h("Final Recommendations")
    bullets(report.final_recommendations)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
