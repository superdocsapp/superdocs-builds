"""PDF export for Interview Preparation Report using ReportLab."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas.report import InterviewPreparationReportDocument
from app.services.report.exporters.common import iter_question_groups, question_fields


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (
        (text or "—")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(safe, style)


def to_pdf_bytes(report: InterviewPreparationReportDocument) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=report.cover_page.title,
        author="Interview Preparation Brief",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=22,
        textColor=colors.HexColor("#15202b"),
        spaceAfter=8,
    )
    h1 = ParagraphStyle(
        "H1",
        parent=styles["Heading1"],
        fontSize=14,
        textColor=colors.HexColor("#0f6f8c"),
        spaceBefore=16,
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#15202b"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#15202b"),
    )
    muted = ParagraphStyle(
        "Muted",
        parent=body,
        textColor=colors.HexColor("#5b6b7c"),
    )

    story: list = []
    cover = report.cover_page
    story.append(_p(cover.title, title_style))
    story.append(
        _p(
            f"{cover.company_name} · {cover.target_role or 'Role TBD'} · "
            f"{cover.candidate_name or 'Candidate'} · {cover.prepared_on.strftime('%Y-%m-%d')}",
            muted,
        )
    )
    story.append(_p(cover.tagline, muted))
    story.append(Spacer(1, 12))

    score_table = Table(
        [[f"Resume Match Score: {report.resume_match_score.score}/100"]],
        colWidths=[6.5 * inch],
    )
    score_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e7f6fb")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0f6f8c")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("PADDING", (0, 0), (-1, -1), 10),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#b7dbe6")),
            ]
        )
    )
    story.append(score_table)
    story.append(Spacer(1, 8))
    story.append(_p(report.resume_match_score.summary, body))

    def section(title: str, text: str) -> None:
        story.append(_p(title, h1))
        story.append(_p(text, body))

    def bullets(title: str, items: list[str]) -> None:
        story.append(_p(title, h1))
        if not items:
            story.append(_p("—", body))
            return
        story.append(
            ListFlowable(
                [ListItem(_p(item, body), leftIndent=10) for item in items],
                bulletType="bullet",
            )
        )

    section("Company Overview", report.company_overview)
    section("Role Summary", report.role_summary)
    bullets("Strengths", report.strengths)
    bullets("Weaknesses", report.weaknesses)

    gap = report.skill_gap or {}
    story.append(_p("Skill Gap", h1))
    story.append(_p(gap.get("summary") or "—", body))
    matching = [
        (s.get("name") if isinstance(s, dict) else getattr(s, "name", ""))
        + (
            f" — {(s.get('evidence') if isinstance(s, dict) else getattr(s, 'evidence', ''))}"
            if (s.get("evidence") if isinstance(s, dict) else getattr(s, "evidence", None))
            else ""
        )
        for s in (gap.get("matching_skills") or [])
    ]
    missing = [
        s.get("name") if isinstance(s, dict) else getattr(s, "name", "")
        for s in (gap.get("missing_skills") or [])
    ]
    bullets("Matching Skills", matching or ["—"])
    bullets("Missing Skills", missing or ["—"])
    bullets("Resume Improvements", report.resume_improvements or ["—"])

    story.append(_p("Interview Questions", h1))
    for title, items in iter_question_groups(report):
        story.append(_p(title, h2))
        for idx, raw in enumerate(items, start=1):
            q = question_fields(raw)
            story.append(_p(f"Q{idx}. {q['question']}", h2))
            story.append(_p(f"Difficulty: {q['difficulty']}", body))
            story.append(_p(f"Expected Answer: {q['expected_answer']}", body))
            story.append(_p(f"Resume Evidence: {q['resume_evidence']}", body))
            story.append(
                _p(
                    "Missing Knowledge: " + (", ".join(q["missing_knowledge"]) or "—"),
                    body,
                )
            )

    story.append(_p("Evidence-backed Answers", h1))
    for idx, ans in enumerate(report.evidence_backed_answers, start=1):
        story.append(_p(f"{idx}. {ans.question}", h2))
        story.append(_p(ans.answer, body))

    story.append(_p("Behavioral Answers", h1))
    if not report.behavioral_answers:
        story.append(_p("—", body))
    for idx, ans in enumerate(report.behavioral_answers, start=1):
        story.append(_p(f"{idx}. {ans.question}", h2))
        story.append(_p(ans.answer, body))

    story.append(_p("STAR Stories", h1))
    for idx, star in enumerate(report.star_stories, start=1):
        story.append(_p(f"{idx}. {star.question}", h2))
        if not star.has_evidence:
            story.append(_p(star.note or "No evidence found.", body))
        else:
            story.append(_p(f"Situation: {star.situation}", body))
            story.append(_p(f"Task: {star.task}", body))
            story.append(_p(f"Action: {star.action}", body))
            story.append(_p(f"Result: {star.result}", body))

    bullets(
        "Revision Plan",
        [
            f"{i.topic} ({i.priority}) — {i.reason} [{i.revision_link}]"
            for i in report.revision_plan
        ],
    )

    story.append(_p("30-60-90 Day Plan", h1))
    for phase in report.day_30_60_90_plan:
        story.append(_p(f"Day {phase.phase}", h2))
        bullets("Goals", phase.goals)
        bullets("Actions", phase.actions)

    bullets("Final Recommendations", report.final_recommendations)
    story.append(Spacer(1, 16))
    story.append(_p("End of Interview Preparation Report", muted))

    doc.build(story)
    return buffer.getvalue()
