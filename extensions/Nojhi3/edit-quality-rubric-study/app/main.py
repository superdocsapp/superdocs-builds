"""FastAPI service for the Edit-Quality Rubric study.

Endpoints
---------
GET  /                     overview + endpoints
GET  /rubric               the rubric (JSON)
GET  /cases                study cases (JSON)
POST /study/edits          run the edit pipeline for given case_ids
POST /study/judge/auto     run the automated judge for given case_ids
GET  /judge                human judge UI (one page, all cases)
POST /judge/submit         save one case's human scores
GET  /study/scores         all score sheets (JSON)
GET  /study/analysis       inter-rater agreement analysis (JSON)
GET  /study/budget         operation spend report (JSON)
GET  /study/report         study report as markdown
GET  /study/report/export  export the report via SuperDocs (docx/pdf/html)
"""

import json
import re
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from . import config
from .analysis import analyze
from .budget import BudgetGuard
from .judges import AutoJudge, load_score_sheets, save_human_scores
from .pipeline import EditRunner, load_cases
from .report import build_report, build_report_html
from .rubric import load_rubric
from .superdocs_client import SuperDocsClient

app = FastAPI(title="Edit-Quality Rubric Study", version="1.0")


def _case_meta():
    return {c["case_id"]: c for c in load_cases()}


@app.get("/")
def index():
    return {
        "name": "Edit-Quality Rubric Study",
        "endpoints": {
            "rubric": "/rubric",
            "cases": "/cases",
            "run_edits": "POST /study/edits?case_ids=plan-01,plan-02",
            "run_auto_judge": "POST /study/judge/auto",
            "human_judge_ui": "/judge",
            "submit_human_scores": "POST /judge/submit",
            "analysis": "/study/analysis",
            "budget": "/study/budget",
            "report": "/study/report",
            "report_export": "GET /study/report/export?format=docx",
        },
    }


@app.get("/rubric")
def get_rubric():
    return load_rubric()


@app.get("/cases")
def get_cases():
    return load_cases()


@app.post("/study/edits")
def run_edits(case_ids: Optional[str] = Query(None, description="comma-separated case ids; empty = all")):
    ids = [c.strip() for c in case_ids.split(",")] if case_ids else None
    runner = EditRunner()
    summary = runner.run_all(ids)
    return {"budget": runner.client.budget.report(), "summary": summary}


@app.post("/study/judge/auto")
def run_auto_judge(case_ids: Optional[str] = Query(None)):
    ids = [c.strip() for c in case_ids.split(",")] if case_ids else None
    judge = AutoJudge()
    summary = judge.judge_all(ids)
    return {"budget": judge.client.budget.report(), "summary": summary}


def _case_html(case_id: str) -> Optional[tuple[str, str]]:
    """(source_html, edited_html) for a case, or None if the edit pipeline
    has not produced an edited document yet."""
    before = config.EDITS_DIR / case_id / "before.html"
    after = config.EDITS_DIR / case_id / "after.html"
    if not after.exists():
        return None
    source = before.read_text(encoding="utf-8") if before.exists() else "<p>(source not available)</p>"
    return source, after.read_text(encoding="utf-8")


@app.get("/judge", response_class=HTMLResponse)
def judge_ui():
    rubric = load_rubric()
    cases = load_cases()
    saved = load_score_sheets("human")
    saved_times = {}
    for cid in cases:
        p = config.HUMAN_DIR / f"{cid['case_id']}.json"
        if p.exists():
            saved_times[cid["case_id"]] = p.stat().st_mtime
    auto_done = len(load_score_sheets("auto"))
    human_done = len(saved)
    cards = []
    for case in cases:
        cid = case["case_id"]
        pair = _case_html(cid)
        if not pair:
            cards.append(
                f"<div class='card'><h3>{cid} — <em>edit not run yet (POST /study/edits first)</em></h3></div>"
            )
            continue
        before_p, after_p = pair
        prev = saved.get(cid, {})
        prev_scores = prev.get("scores", {})
        prev_evidence = prev.get("evidence", {})
        dims = "".join(
            f"""
            <div class='dim'>
              <label><b>{d['label']}</b><br><span class='desc'>{d['description']}</span></label>
              <div class='scale'>
                {''.join(f"<label class='opt'><input type='radio' name='{d['id']}' value='{s}'{' checked' if prev_scores.get(d['id']) == s else ''}>{s}</label>"
                         for s in range(1, 5))}
              </div>
              <textarea name='ev_{d['id']}' rows='2' placeholder='evidence (optional): quote the passage that justifies your score'>{html_escape(prev_evidence.get(d['id'], ''))}</textarea>
            </div>"""
            for d in rubric["dimensions"]
        )
        saved_badge = ""
        if cid in saved_times:
            ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(saved_times[cid]))
            saved_badge = f"<span class='badge saved'>saved {ts}</span>"
        cards.append(
            f"""
            <div class='card' id='{cid}'>
              <h3>{cid} <span class='diff'>{case['difficulty']}</span> {saved_badge}</h3>
              <p class='instruction'><b>Instruction:</b> {html_escape(case['instruction'])}</p>
              <details><summary>Source document</summary><div class='doc'>{before_p}</div></details>
              <details open><summary>Edited document</summary><div class='doc'>{after_p}</div></details>
              <form class='scores' data-case='{cid}'>{dims}
                <button type='submit'>Save scores</button> <span class='status'></span>
              </form>
            </div>"""
        )
    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
    <title>Human judge - Edit Quality Rubric</title>
    <style>
      body{{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:1em auto;padding:0 1em}}
      .card{{border:1px solid #ccc;border-radius:8px;padding:1em;margin:1em 0}}
      .card h3{{margin:0 0 .3em 0}}.diff{{background:#eee;padding:2px 8px;border-radius:10px;font-size:.8em;font-weight:normal}}
      .badge{{font-size:.75em;padding:2px 8px;border-radius:10px}}
      .badge.saved{{background:#e6f4ea;color:#0a7d32}}
      .instruction{{margin:.2em 0 .6em 0}}
      .doc{{border:1px solid #ddd;background:#fafafa;padding:.8em;max-height:420px;overflow:auto;font-size:.92em}}
      .doc table{{border-collapse:collapse}}.doc td,.doc th{{border:1px solid #999;padding:3px 7px}}
      .dim{{margin:.8em 0;border-left:3px solid #eee;padding-left:.6em}}
      .desc{{color:#666;font-weight:normal;font-size:.85em}}
      .scale{{margin:.3em 0}}.opt{{margin-right:.8em}}
      textarea{{width:98%}}
      .status{{margin-left:1em;color:#0a7d32}}
      details{{margin:.3em 0}}
      #progress{{font-size:.95em;color:#333;margin:.5em 0}}
    </style></head><body>
    <h1>Human judge: score each edit on the rubric</h1>
    <p id='progress'>Saved sheets: human <b>{human_done}/{len(cases)}</b> &middot; automated <b>{auto_done}/{len(cases)}</b>.
    Saved scores are restored when you reload. Re-saving overwrites.</p>
    <p>Score 1=Fail, 2=Poor, 3=Good, 4=Excellent. Evidence is optional but makes disagreements reviewable.
    Judge the edit quality, not the source document. You see the same material the automated judge saw.</p>
    {''.join(cards)}
    <script>
      document.querySelectorAll('form.scores').forEach(f => f.addEventListener('submit', async e => {{
        e.preventDefault();
        const cid = f.dataset.case;
        const scores = {{}}; const evidence = {{}};
        f.querySelectorAll('input[type=radio]:checked').forEach(i => scores[i.name] = parseInt(i.value));
        f.querySelectorAll('textarea').forEach(t => evidence[t.name.replace('ev_','')] = t.value);
        const res = await fetch('/judge/submit', {{method:'POST', headers:{{'Content-Type':'application/json'}},
          body: JSON.stringify({{case_id: cid, scores, evidence}})}});
        const st = f.querySelector('.status');
        if (res.ok) {{
          st.textContent = 'saved';
          const badge = document.getElementById(cid).querySelector('.badge.saved');
          if (!badge) {{
            const b = document.createElement('span');
            b.className = 'badge saved'; b.textContent = 'saved now';
            document.getElementById(cid).querySelector('h3').appendChild(b);
          }}
        }} else {{
          st.textContent = 'error: ' + (await res.text());
        }}
      }}));
    </script></body></html>"""
    return html


def _html_escape(text: str) -> str:
    return re.sub(r"[<>&]", lambda m: {"<": "&lt;", ">": "&gt;", "&": "&amp;"}[m.group()], text)


# patch into module namespace for the f-string above
html_escape = _html_escape


@app.post("/judge/submit")
def submit_human_scores(payload: dict):
    case_id = payload.get("case_id")
    scores = payload.get("scores") or {}
    evidence = payload.get("evidence") or {}
    if case_id not in _case_meta():
        raise HTTPException(404, f"unknown case {case_id}")
    if not isinstance(scores, dict) or not isinstance(evidence, dict):
        raise HTTPException(422, "scores and evidence must be JSON objects")
    try:
        sheet = save_human_scores(case_id, scores, evidence)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "sheet": sheet}


@app.get("/study/scores")
def get_scores():
    return {"human": load_score_sheets("human"), "auto": load_score_sheets("auto")}


@app.get("/study/analysis")
def get_analysis():
    human, auto = load_score_sheets("human"), load_score_sheets("auto")
    if not human or not auto:
        raise HTTPException(409, "need both human and auto score sheets first")
    return analyze(human, auto, _case_meta())


@app.get("/study/budget")
def get_budget():
    return BudgetGuard().report()


@app.get("/study/report", response_class=PlainTextResponse)
def get_report():
    return build_report()


@app.get("/study/report/export")
def export_report(format: str = Query("docx", pattern="^(docx|pdf|html|markdown|txt)$")):
    """Export the study report through SuperDocs' export endpoint."""
    try:
        html_content = build_report_html()
        client = SuperDocsClient()
        data = client.export(html=html_content, fmt=format, filename="edit-quality-rubric-study-report")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"export failed: {exc}") from exc
    media = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "html": "text/html",
        "markdown": "text/markdown",
        "txt": "text/plain",
    }[format]
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="edit-quality-rubric-study-report.{format}"'})