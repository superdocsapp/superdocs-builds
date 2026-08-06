"""HTML export with professional formatting."""

from __future__ import annotations

import html

from app.schemas.report import InterviewPreparationReportDocument
from app.services.report.exporters.common import iter_question_groups, question_fields


def _e(value: str | None) -> str:
    return html.escape(value or "—")


def to_html(report: InterviewPreparationReportDocument) -> str:
    cover = report.cover_page
    gap = report.skill_gap or {}

    strength_lis = "".join(f"<li>{_e(s)}</li>" for s in report.strengths)
    weakness_lis = "".join(f"<li>{_e(w)}</li>" for w in report.weaknesses)
    improve_lis = "".join(f"<li>{_e(i)}</li>" for i in (report.resume_improvements or ["—"]))
    matching_lis = "".join(
        f"<li><strong>{_e(s.get('name') if isinstance(s, dict) else getattr(s, 'name', ''))}</strong>"
        f"{(' — ' + _e(s.get('evidence') if isinstance(s, dict) else getattr(s, 'evidence', None))) if (s.get('evidence') if isinstance(s, dict) else getattr(s, 'evidence', None)) else ''}</li>"
        for s in (gap.get("matching_skills") or [])
    ) or "<li>—</li>"
    missing_lis = "".join(
        f"<li>{_e(s.get('name') if isinstance(s, dict) else getattr(s, 'name', ''))}</li>"
        for s in (gap.get("missing_skills") or [])
    ) or "<li>—</li>"

    question_sections = []
    for title, items in iter_question_groups(report):
        cards = []
        for idx, raw in enumerate(items, start=1):
            q = question_fields(raw)
            links = "".join(
                f'<li><a href="{_e(link.get("url") if isinstance(link, dict) else getattr(link, "url", "#"))}">'
                f'{_e(link.get("title") if isinstance(link, dict) else getattr(link, "title", "Revise"))}</a></li>'
                for link in q["revision_links"]
            ) or "<li>—</li>"
            cards.append(
                f"""
                <article class="card">
                  <h4>Q{idx}. {_e(q['question'])}</h4>
                  <ul class="meta">
                    <li><strong>Difficulty:</strong> {_e(str(q['difficulty']))}</li>
                    <li><strong>Expected Answer:</strong> {_e(q['expected_answer'])}</li>
                    <li><strong>Resume Evidence:</strong> {_e(q['resume_evidence'])}</li>
                    <li><strong>Missing Knowledge:</strong> {_e(', '.join(q['missing_knowledge']) or '—')}</li>
                  </ul>
                  <p><strong>Revision Links</strong></p>
                  <ul>{links}</ul>
                </article>
                """
            )
        question_sections.append(f"<h3>{_e(title)}</h3>{''.join(cards)}")

    evidence_blocks = []
    for idx, ans in enumerate(report.evidence_backed_answers, start=1):
        spans = "".join(f"<li>{_e(s)}</li>" for s in ans.evidence_spans) or "<li>—</li>"
        evidence_blocks.append(
            f"<article class='card'><h4>{idx}. {_e(ans.question)}</h4>"
            f"<p>{_e(ans.answer)}</p><p><strong>Evidence</strong></p><ul>{spans}</ul></article>"
        )

    behavioral_blocks = []
    for idx, ans in enumerate(report.behavioral_answers, start=1):
        behavioral_blocks.append(
            f"<article class='card'><h4>{idx}. {_e(ans.question)}</h4><p>{_e(ans.answer)}</p></article>"
        )
    if not behavioral_blocks:
        behavioral_blocks = ["<p>—</p>"]

    star_blocks = []
    for idx, star in enumerate(report.star_stories, start=1):
        if not star.has_evidence:
            body = f"<p>{_e(star.note or 'No evidence found.')}</p>"
        else:
            body = (
                f"<ul><li><strong>Situation:</strong> {_e(star.situation)}</li>"
                f"<li><strong>Task:</strong> {_e(star.task)}</li>"
                f"<li><strong>Action:</strong> {_e(star.action)}</li>"
                f"<li><strong>Result:</strong> {_e(star.result)}</li></ul>"
            )
        star_blocks.append(f"<article class='card'><h4>{idx}. {_e(star.question)}</h4>{body}</article>")

    revision_lis = "".join(
        f"<li><strong>{_e(i.topic)}</strong> ({_e(i.priority)}) — {_e(i.reason)} "
        f"<a href='{_e(i.revision_link)}'>Revise</a></li>"
        for i in report.revision_plan
    )
    roadmap_blocks = []
    for phase in report.day_30_60_90_plan:
        goals = "".join(f"<li>{_e(g)}</li>" for g in phase.goals)
        actions = "".join(f"<li>{_e(a)}</li>" for a in phase.actions)
        roadmap_blocks.append(
            f"<article class='card'><h4>Day {_e(phase.phase)}</h4>"
            f"<p><strong>Goals</strong></p><ul>{goals}</ul>"
            f"<p><strong>Actions</strong></p><ul>{actions}</ul></article>"
        )
    rec_lis = "".join(f"<li>{_e(r)}</li>" for r in report.final_recommendations)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_e(cover.title)} — {_e(cover.company_name)}</title>
  <style>
    :root {{
      --ink: #15202b;
      --muted: #5b6b7c;
      --line: #d7dee7;
      --bg: #f7fafc;
      --card: #ffffff;
      --accent: #0f6f8c;
    }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      color: var(--ink);
      background: linear-gradient(180deg, #eef6f9 0%, var(--bg) 220px);
      line-height: 1.55;
    }}
    .page {{
      max-width: 880px;
      margin: 0 auto;
      padding: 48px 24px 80px;
    }}
    .cover {{
      border: 1px solid var(--line);
      background: var(--card);
      border-radius: 18px;
      padding: 40px 36px;
      margin-bottom: 28px;
      box-shadow: 0 10px 30px rgba(21, 32, 43, 0.06);
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 12px;
      color: var(--accent);
      font-weight: 700;
      margin: 0 0 12px;
    }}
    h1, h2, h3, h4 {{ line-height: 1.25; margin-top: 0; }}
    h1 {{ font-size: 34px; margin-bottom: 10px; }}
    h2 {{
      font-size: 22px;
      border-bottom: 2px solid var(--accent);
      padding-bottom: 8px;
      margin: 36px 0 16px;
    }}
    h3 {{ font-size: 18px; margin: 24px 0 12px; }}
    .meta {{ color: var(--muted); }}
    .score {{
      display: inline-block;
      background: #e7f6fb;
      color: var(--accent);
      border-radius: 999px;
      padding: 6px 14px;
      font-weight: 700;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px 18px;
      margin: 12px 0;
    }}
    ul {{ padding-left: 1.2rem; }}
    a {{ color: var(--accent); }}
    footer {{
      margin-top: 40px;
      color: var(--muted);
      font-size: 13px;
      border-top: 1px solid var(--line);
      padding-top: 16px;
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="cover">
      <p class="eyebrow">Interview Preparation Brief</p>
      <h1>{_e(cover.title)}</h1>
      <p class="meta">
        <strong>Company:</strong> {_e(cover.company_name)} ·
        <strong>Role:</strong> {_e(cover.target_role)} ·
        <strong>Candidate:</strong> {_e(cover.candidate_name)} ·
        <strong>Prepared:</strong> {_e(cover.prepared_on.strftime('%Y-%m-%d %H:%M UTC'))}
      </p>
      <p>{_e(cover.tagline)}</p>
    </section>

    <h2>Company Overview</h2>
    <p>{_e(report.company_overview)}</p>

    <h2>Role Summary</h2>
    <p>{_e(report.role_summary)}</p>

    <h2>Resume Match Score</h2>
    <p><span class="score">{report.resume_match_score.score}/100</span></p>
    <p>{_e(report.resume_match_score.summary)}</p>

    <h2>Strengths</h2>
    <ul>{strength_lis}</ul>

    <h2>Weaknesses</h2>
    <ul>{weakness_lis}</ul>

    <h2>Skill Gap</h2>
    <p>{_e(gap.get('summary'))}</p>
    <h3>Matching Skills</h3>
    <ul>{matching_lis}</ul>
    <h3>Missing Skills</h3>
    <ul>{missing_lis}</ul>

    <h2>Resume Improvements</h2>
    <ul>{improve_lis}</ul>

    <h2>Interview Questions</h2>
    {''.join(question_sections) or '<p>—</p>'}

    <h2>Evidence-backed Answers</h2>
    {''.join(evidence_blocks) or '<p>—</p>'}

    <h2>Behavioral Answers</h2>
    {''.join(behavioral_blocks)}

    <h2>STAR Stories</h2>
    {''.join(star_blocks) or '<p>—</p>'}

    <h2>Revision Plan</h2>
    <ul>{revision_lis}</ul>

    <h2>30-60-90 Day Plan</h2>
    {''.join(roadmap_blocks) or '<p>—</p>'}

    <h2>Final Recommendations</h2>
    <ul>{rec_lis}</ul>

    <footer>End of Interview Preparation Report · Evidence-grounded · No fabricated experience</footer>
  </div>
</body>
</html>
"""
