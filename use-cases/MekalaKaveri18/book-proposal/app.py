from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
LIB = ROOT.parent / "_lib"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(ROOT))

from catalog import draft_instruction, proposal_items, search_comparables  # noqa: E402
from gate import items_to_queue, record_decision  # noqa: E402
from superdocs import SuperDocs, SuperDocsError, load_dotenv, parse_pending_changes  # noqa: E402

load_dotenv(ROOT.parent / ".env")

app = FastAPI(title="Book proposal builder")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

JOBS: dict[str, dict] = {}
TEMPLATE = (ROOT / "templates" / "proposal.html").read_text(encoding="utf-8")


class ProposalIn(BaseModel):
    title: str
    author: str
    overview: str
    audience: str
    chapters: str
    search_query: str = ""
    review_mode: bool = True
    sample: bool = False


class DecisionIn(BaseModel):
    decisions: dict[str, bool] = Field(default_factory=dict)


@app.get("/")
def index():
    return HTMLResponse((ROOT / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
def health():
    sd = SuperDocs()
    return {"ok": True, "superdocs": sd.enabled()}


@app.post("/search")
def search(body: dict):
    q = str(body.get("query") or "")
    return {"hits": search_comparables(q, limit=int(body.get("limit") or 3))}


@app.post("/jobs")
def start(body: ProposalIn):
    comps = search_comparables(body.search_query or body.audience or body.overview, limit=3)
    items = proposal_items(body.model_dump(), comps)
    from gate import preview_html

    if body.review_mode or body.sample or not SuperDocs().enabled():
        local_id = f"local-{uuid.uuid4()}"
        if not body.review_mode:
            filled = preview_html(TEMPLATE, items, {c["change_id"]: True for c in items})
            JOBS[local_id] = {
                "mode": "offline",
                "status": "completed",
                "html": filled,
                "baseline_html": TEMPLATE,
                "comps": comps,
                "session_id": local_id,
                "changes": [],
                "queue": items,
                "decisions": {c["change_id"]: True for c in items},
                "applied": True,
                "register": [{"change_id": c["change_id"], "label": c["ai_explanation"], "decision": True} for c in items],
            }
            return _job_out(local_id)
        rec = items_to_queue(items)
        rec["baseline_html"] = TEMPLATE
        rec["html"] = TEMPLATE
        rec["comps"] = comps
        rec["session_id"] = local_id
        JOBS[local_id] = rec
        return _job_out(local_id)

    sd = SuperDocs()
    session_id = f"book-proposal-{uuid.uuid4()}"
    try:
        sd.upload_template("proposal-template.html", TEMPLATE.encode("utf-8"), "text/html")
    except SuperDocsError:
        pass
    try:
        job_id = sd.chat_async(
            session_id,
            draft_instruction(body.model_dump(), comps),
            document_html=preview_html(TEMPLATE, items, {c["change_id"]: True for c in items}),
            approval_mode="approve_all",
        )
        polled = sd.poll_job(job_id)
    except SuperDocsError as e:
        raise HTTPException(502, str(e)) from e
    JOBS[job_id] = {
        "mode": "live",
        "session_id": session_id,
        "job": polled,
        "comps": comps,
        "baseline_html": TEMPLATE,
        "html": _html_from_job(polled) or preview_html(TEMPLATE, items, {c["change_id"]: True for c in items}),
        "changes": [],
        "queue": items,
        "status": polled.get("status"),
        "register": [{"change_id": c["change_id"], "label": c["ai_explanation"], "decision": True} for c in items],
        "applied": True,
    }
    return _job_out(job_id)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "job not found")
    return _job_out(job_id)


@app.post("/jobs/{job_id}/review")
def review(job_id: str, body: DecisionIn):
    rec = JOBS.get(job_id)
    if not rec:
        raise HTTPException(404, "job not found")
    record_decision(rec, body.decisions)
    return _job_out(job_id)


@app.get("/jobs/{job_id}/export")
def export(job_id: str, fmt: str = "docx"):
    rec = JOBS.get(job_id)
    if not rec:
        raise HTTPException(404, "job not found")
    html = rec.get("html") or TEMPLATE
    sd = SuperDocs()
    if rec["mode"] == "live" and sd.enabled():
        try:
            data = sd.export(session_id=rec["session_id"], html=html, fmt=fmt, filename="book-proposal")
            return Response(data, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename=book-proposal.{fmt}"})
        except SuperDocsError as e:
            raise HTTPException(502, str(e)) from e
    path = ROOT / "exports"
    path.mkdir(exist_ok=True)
    out = path / f"book-proposal-{job_id[:8]}.html"
    out.write_text(html, encoding="utf-8")
    return FileResponse(out, filename="book-proposal.html")


def _html_from_job(job: dict) -> str:
    result = job.get("result") or {}
    changes = result.get("document_changes") or {}
    return changes.get("updated_html") or result.get("updated_html") or ""


def _offline_fill(body: ProposalIn, comps: list[dict]) -> str:
    market = "\n".join(
        f"<li><strong>{c['title']}</strong> — {c['author']} ({c['year']}, {c['publisher']}; ISBN {c['isbn']}). {c['why_comp']}</li>"
        for c in comps
    )
    chapters = "".join(f"<li>{line.strip()}</li>" for line in body.chapters.splitlines() if line.strip())
    return f"""<h1>{body.title}</h1>
<p><em>{body.author}</em></p>
<h2>One-sentence overview</h2><p>{body.overview}</p>
<h2>Market: comparable titles</h2><ul>{market}</ul>
<h2>Audience</h2><p>{body.audience}</p>
<h2>Chapter outline</h2><ol>{chapters}</ol>
<p>Offline sample fill. Connect SUPERDOCS_API_KEY for SuperDocs HITL edit, template reuse, and export.</p>
"""


def _job_out(job_id: str) -> dict:
    rec = JOBS[job_id]
    status = rec.get("status")
    if rec.get("mode") == "live" and rec.get("job") and not rec.get("queue"):
        status = rec["job"].get("status")
    changes = rec.get("changes") or []
    if rec.get("mode") == "live" and rec.get("job") and rec.get("status") not in ("awaiting_approval", "completed"):
        changes = parse_pending_changes(rec["job"])
    return {
        "id": job_id,
        "status": status,
        "offline": rec.get("mode") != "live",
        "comps": rec.get("comps"),
        "html": rec.get("html"),
        "changes": changes,
        "register": rec.get("register") or [],
        "applied": rec.get("applied"),
        "error": (rec.get("job") or {}).get("error") if rec.get("job") else None,
    }
