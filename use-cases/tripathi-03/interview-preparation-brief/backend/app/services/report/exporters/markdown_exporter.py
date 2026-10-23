"""Markdown export for Interview Preparation Report."""

from __future__ import annotations

from app.schemas.report import InterviewPreparationReportDocument
from app.services.report.exporters.common import iter_question_groups, question_fields


def to_markdown(report: InterviewPreparationReportDocument) -> str:
    cover = report.cover_page
    lines: list[str] = [
        f"# {cover.title}",
        "",
        f"**Company:** {cover.company_name}  ",
        f"**Role:** {cover.target_role or '—'}  ",
        f"**Candidate:** {cover.candidate_name or '—'}  ",
        f"**Prepared:** {cover.prepared_on.strftime('%Y-%m-%d %H:%M UTC')}  ",
        "",
        f"*{cover.tagline}*",
        "",
        "---",
        "",
        "## Company Overview",
        "",
        report.company_overview or "—",
        "",
        "## Role Summary",
        "",
        report.role_summary or "—",
        "",
        "## Resume Match Score",
        "",
        f"**Score:** {report.resume_match_score.score}/100  ",
        report.resume_match_score.summary,
        "",
        "## Strengths",
        "",
    ]
    lines.extend(f"- {s}" for s in report.strengths)
    lines += ["", "## Weaknesses", ""]
    lines.extend(f"- {w}" for w in report.weaknesses)

    lines += ["", "## Skill Gap", ""]
    gap = report.skill_gap or {}
    lines.append(gap.get("summary") or "—")
    lines += ["", "### Matching Skills", ""]
    for skill in gap.get("matching_skills") or []:
        name = skill.get("name") if isinstance(skill, dict) else getattr(skill, "name", "")
        evidence = skill.get("evidence") if isinstance(skill, dict) else getattr(skill, "evidence", None)
        lines.append(f"- **{name}**" + (f" — {evidence}" if evidence else ""))
    lines += ["", "### Missing Skills", ""]
    for skill in gap.get("missing_skills") or []:
        name = skill.get("name") if isinstance(skill, dict) else getattr(skill, "name", "")
        lines.append(f"- {name}")

    lines += ["", "## Resume Improvements", ""]
    lines.extend(f"- {item}" for item in (report.resume_improvements or ["—"]))

    lines += ["", "## Interview Questions", ""]
    for title, items in iter_question_groups(report):
        lines += [f"### {title}", ""]
        for idx, raw in enumerate(items, start=1):
            q = question_fields(raw)
            lines += [
                f"#### Q{idx}. {q['question']}",
                "",
                f"- **Difficulty:** {q['difficulty']}",
                f"- **Expected Answer:** {q['expected_answer']}",
                f"- **Resume Evidence:** {q['resume_evidence']}",
                f"- **Missing Knowledge:** {', '.join(q['missing_knowledge']) or '—'}",
            ]
            if q["revision_links"]:
                links = []
                for link in q["revision_links"]:
                    if isinstance(link, dict):
                        links.append(f"[{link.get('title', 'Revise')}]({link.get('url', '#')})")
                    else:
                        links.append(f"[{getattr(link, 'title', 'Revise')}]({getattr(link, 'url', '#')})")
                lines.append(f"- **Revision Links:** {', '.join(links)}")
            lines.append("")

    lines += ["", "## Evidence-backed Answers", ""]
    for idx, ans in enumerate(report.evidence_backed_answers, start=1):
        lines += [
            f"### {idx}. {ans.question}",
            "",
            ans.answer,
            "",
        ]
        if ans.evidence_spans:
            lines.append("Evidence:")
            lines.extend(f"- {span}" for span in ans.evidence_spans)
            lines.append("")

    lines += ["", "## Behavioral Answers", ""]
    if not report.behavioral_answers:
        lines.append("—")
    for idx, ans in enumerate(report.behavioral_answers, start=1):
        lines += [f"### {idx}. {ans.question}", "", ans.answer, ""]

    lines += ["", "## STAR Stories", ""]
    for idx, star in enumerate(report.star_stories, start=1):
        lines += [f"### {idx}. {star.question}", ""]
        if not star.has_evidence:
            lines += [star.note or "No evidence found.", ""]
        else:
            lines += [
                f"- **Situation:** {star.situation}",
                f"- **Task:** {star.task}",
                f"- **Action:** {star.action}",
                f"- **Result:** {star.result}",
                "",
            ]

    lines += ["", "## Revision Plan", ""]
    for item in report.revision_plan:
        lines.append(
            f"- **{item.topic}** ({item.priority}) — {item.reason} "
            f"[Revise]({item.revision_link})"
        )

    lines += ["", "## 30-60-90 Day Plan", ""]
    for phase in report.day_30_60_90_plan:
        lines += [f"### Day {phase.phase}", "", "**Goals**"]
        lines.extend(f"- {g}" for g in phase.goals)
        lines += ["", "**Actions**"]
        lines.extend(f"- {a}" for a in phase.actions)
        lines.append("")

    lines += ["", "## Final Recommendations", ""]
    lines.extend(f"- {r}" for r in report.final_recommendations)

    lines += ["", "---", "", "*End of Interview Preparation Report*"]
    return "\n".join(lines)
