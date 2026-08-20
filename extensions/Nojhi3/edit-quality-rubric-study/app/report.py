"""Assemble the study report: markdown for the repo, HTML for the SuperDocs
export surface (the deliverable proves the export call with the report itself).
"""

import html
import re
from datetime import datetime, timezone

from . import config
from .analysis import analyze
from .budget import BudgetGuard
from .judges import load_score_sheets
from .pipeline import load_cases
from .rubric import load_rubric


def _esc(text):
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _case_meta():
    return {c["case_id"]: c for c in load_cases()}


def build_report(budget=None):
    budget = budget or BudgetGuard()
    rubric = load_rubric()
    human, auto = load_score_sheets("human"), load_score_sheets("auto")
    meta = _case_meta()
    spend = budget.report()
    lines = []
    a = lines.append

    a("# Edit-Quality Rubric and Human-vs-Automated Inter-Rater Agreement Study")
    a("")
    a(f"*Study run: {datetime.now(timezone.utc).isoformat()}*")
    a("")
    a("## 1. What this study is")
    a("")
    a("This extension scores the quality of SuperDocs document edits against a "
      "6-dimension rubric, then measures agreement between a human judge and an "
      "automated LLM judge. The automated judge is a general-purpose LLM "
      "(Gemini by default), run blind (instruction + source + edited document, "
      "never the human's scores). "
      "The point is honest reporting: where the automated judge is unreliable, "
      "the report says so.")
    a("")
    a("## 2. Method")
    a("")
    a("**The four-call contract.** Every edit used the SuperDocs minimum contract: "
      "`upload` (POST /v1/documents/upload-base64) -> `chat` (POST /v1/chat/async, "
      "approval_mode=ask_every_time) -> `approve` (POST /v1/chat/{session}/approve, "
      "every proposed change approved atomically) -> `export` (POST /v1/documents/export). "
      "Every billable call is in the operation ledger (`data/ledger.jsonl`).")
    a("")
    a("**Rubric.** Six dimensions, ordinal 1-4 with written anchors (see `data/rubric.json`):")
    a("")
    for d in rubric["dimensions"]:
        a(f"- **{d['label']}** (`{d['id']}`) - {d['description']}")
    a("")
    a("**Cases.**")
    a("")
    a("| case_id | document | difficulty | instruction |")
    a("| --- | --- | --- | --- |")
    for c in load_cases():
        a(f"| {c['case_id']} | {c['doc_id']} | {c['difficulty']} | {_esc(c['instruction'])} |")
    a("")
    a("**Judges.**")
    a("")
    a("- **Human** - one human rater, judging from the same before/after material, scoring independently.")
    a("- **Automated** - general-purpose LLM, same rubric, blind. "
      "A pilot finding: SuperDocs' own chat model is an editing assistant and "
      "does not reliably emit JSON scores (see README), so the judge defaults "
      "to an external LLM and the token spend is recorded separately.")
    a("")
    a("## 3. Budget guard (stated before the run)")
    a("")
    a(f"The full-study cap was stated before any run: **{spend['cap_ops']} operations**. "
      "Each edit bills 1 operation, so a full run expects ~1 edit operation per case "
      "plus any re-runs (re-runs are visible in the ledger below). Automated judging "
      "uses a separate external-LLM ledger (`data/ledger_gemini.jsonl`, token spend, "
      "0 SuperDocs operations). Reads, uploads, approvals, and exports bill 0. "
      "Every call is recorded in `data/ledger.jsonl`.")
    a("")
    a("## 4. Actual spend")
    a("")
    a(f"**Spent: {spend['spent_ops']} operations** (cap {spend['cap_ops']}). "
      f"Billable calls: {spend['billable_calls']} of {spend['total_calls_recorded']} recorded.")
    a("")
    if spend["entries"]:
        a("| time (UTC) | endpoint | tag | billable | ops | remaining |")
        a("| --- | --- | --- | --- | --- | --- |")
        for e in spend["entries"]:
            a(f"| {e.get('iso', '')} | {e.get('endpoint', '')} | {_esc(e.get('tag', ''))} "
              f"| {e.get('was_billable')} | {e.get('ops_charged')} | {e.get('monthly_remaining')} |")
        a("")
    a("## 5. Scores")
    a("")
    a("Human and automated scores per case and dimension (1=Fail ... 4=Excellent):")
    a("")
    a("| case | difficulty | dim | human | auto | diff |")
    a("| --- | --- | --- | --- | --- | --- |")
    for cid in meta:
        h, a_s = (human.get(cid) or {}).get("scores"), (auto.get(cid) or {}).get("scores")
        if not h:
            a(f"| {cid} | {meta[cid]['difficulty']} | (pending) | - | - | |")
            continue
        a(f"| {cid} | {meta[cid]['difficulty']} | (total) | "
          f"{sum(h.values())}/24 | {sum(a_s.values())}/24 | |")
        for d in rubric["dimensions"]:
            did = d["id"]
            a(f"| {cid} | | {did} | {h[did]} | {a_s[did]} | {h[did] - a_s[did]:+d} |")
    a("")
    a("## 6. Inter-rater agreement (human vs automated)")
    a("")
    if not (human and auto and set(human) & set(auto)):
        a("Agreement statistics are computed once both raters have scored the "
          "same cases. Human sheets on disk: "
          f"{len(human)}; auto sheets: {len(auto)}.")
        a("")
    else:
        analysis = analyze(human, auto, meta)
        o = analysis["overall"]
        a(f"**Overall:** percent exact agreement {o['percent_agreement']:.1%} over "
          f"{o['n_judgments']} judgments ({o['n_cases']} cases x {len(rubric['dimensions'])} dimensions); "
          f"Cohen's kappa **{o['kappa']}** (95% CI {o['kappa_ci95']}); "
          f"linear-weighted kappa **{o['kappa_linear_weighted']}**.")
        a("")
        a("Per dimension:")
        a("")
        a("| dimension | n | % exact | kappa | kappa 95% CI | band | weighted kappa |")
        a("| --- | --- | --- | --- | --- | --- | --- |")
        for d in rubric["dimensions"]:
            dim = analysis["dimensions"][d["id"]]
            a(f"| {dim['label']} | {dim['n']} | {dim['percent_agreement']:.1%} "
              f"| {dim['kappa']} | {dim['kappa_ci95']} | {dim['kappa_band']} "
              f"| {dim['kappa_linear_weighted']} |")
        a("")
        a("Score distribution per rater (count of 1-4 judgments):")
        a("")
        a("| score | human | auto |")
        a("| --- | --- | --- |")
        for v in ("1", "2", "3", "4"):
            a(f"| {v} | {analysis['distributions']['human'].get(v, 0)} | "
              f"{analysis['distributions']['auto'].get(v, 0)} |")
        a("")
        a("Confusion matrices per dimension (rows = human, columns = automated; "
          "diagonal cells are exact agreements):")
        a("")
        for d in rubric["dimensions"]:
            cm = analysis["dimensions"][d["id"]]["confusion"]
            a(f"**{d['label']}** (`{d['id']}`)")
            a("")
            a("| human \\ auto | 1 | 2 | 3 | 4 |")
            a("| --- | --- | --- | --- | --- |")
            for h in (1, 2, 3, 4):
                a(f"| {h} | {' | '.join(str(cm[h][c]) for c in (1, 2, 3, 4))} |")
            a("")
        a("")
        a("## 7. Disagreement review (where the automated judge is unreliable)")
        a("")
        if not analysis["disagreements"]:
            a("No disagreements of 2+ scale points were found in this sample.")
        else:
            a(f"{len(analysis['disagreements'])} judgments disagreed by 2+ scale points. "
              "Each row cites both raters' evidence.")
            a("")
            for dis in analysis["disagreements"]:
                a(f"### {dis['case_id']} / `{dis['dimension']}` - human {dis['human']} vs auto {dis['auto']} (diff {dis['diff']:+d})")
                a(f"*Difficulty: {dis['difficulty']}*")
                a(f"- Instruction: {_esc(dis['instruction'])}")
                a(f"- Human evidence: {_esc(dis['human_evidence'])}")
                a(f"- Auto evidence: {_esc(dis['auto_evidence'])}")
                a("")
    a("## 8. Honest limitations")
    a("")
    a("- **Small sample.** This is a small-sample study by design (budget guard first). "
      "Kappa 95% CIs are wide and must not be read as precise estimates.")
    a("- **Single human rater.** Agreement here is human-1 vs auto, not a gold standard; "
      "human-human agreement would need a second rater.")
    a("- **Sparse human evidence.** The human rater recorded written evidence for only "
      "a few dimensions (plan-04); most disagreement rows therefore carry only the "
      "automated judge's evidence. Score differences are still reviewable from the "
      "before/after material in `data/edits/`.")
    a("- **Ordinal scale ceiling.** Dimensions on which every case scores 3-4 (or 1-2) "
      "compress kappa even when raters agree on ranking; weighted kappa partially compensates.")
    a("- **Blindness limits.** The automated judge sees text; visual formatting "
      "regressions in the final rendered file may not be visible to it - treated "
      "honestly per dimension in the evidence.")
    a("")
    a("## 9. Reproduce")
    a("")
    a("```bash")
    a("pip install -r requirements.txt")
    a("python scripts/run_study.py --small   # or --full; cap enforced in app/budget.py")
    a("uvicorn app.main:app                   # judge UI at /judge, report at /report")
    a("```")
    a("")
    a("Every artifact is on disk: `data/edits/<case_id>/` (upload, pending changes, approve, "
      "job result, before/after HTML, exported docx) and `data/judgments/` (score sheets).")
    return "\n".join(lines)


def _md_to_html(md: str) -> str:
    """Minimal markdown -> HTML for the export surface: headings, tables,
    bold, inline code, fenced code blocks, lists, paragraphs."""
    html_parts = []
    in_code = False
    in_table = False
    table_rows = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                html_parts.append("</pre>")
                in_code = False
            else:
                html_parts.append("<pre>")
                in_code = True
            continue
        if in_code:
            html_parts.append(html.escape(line))
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not in_table:
                in_table = True
                table_rows = []
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue
            table_rows.append(cells)
            continue
        if in_table:
            html_parts.append(_table_html(table_rows))
            table_rows = []
            in_table = False
        if not line:
            continue
        if line.startswith("# "):
            html_parts.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            html_parts.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            html_parts.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("#### "):
            html_parts.append(f"<h4>{_inline(line[5:])}</h4>")
        elif line.startswith("- "):
            html_parts.append(f"<li>{_inline(line[2:])}</li>")
        else:
            html_parts.append(f"<p>{_inline(line)}</p>")
    if in_table:
        html_parts.append(_table_html(table_rows))
    return "\n".join(html_parts)


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def _table_html(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    out = ["<table>"]
    for i, row in enumerate(rows):
        tag = "th" if i == 0 else "td"
        out.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in row) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def build_report_html(budget=None):
    """Markdown -> HTML for the SuperDocs export surface."""
    md = build_report(budget)
    body = _md_to_html(md)
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>Edit-Quality Rubric Study Report</title>"
            "<style>body{font-family:Georgia,serif;max-width:900px;margin:2em auto;padding:0 1em;"
            "line-height:1.5}table{border-collapse:collapse;width:100%}th,td{border:1px solid #999;"
            "padding:4px 8px;font-size:14px}th{background:#eee}code{background:#f4f4f4;padding:1px 3px}"
            "pre{background:#f4f4f4;padding:8px;overflow-x:auto}</style></head><body>"
            + body + "</body></html>")