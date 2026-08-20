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

from catalog import draft_instruction, search_comparables  # noqa: E402
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
    html = TEMPLATE
    if body.sample or not SuperDocs().enabled():
        local_id = f"local-{uuid.uuid4()}"
        html = _offline_fill(body, comps)
        JOBS[local_id] = {
            "mode": "offline",
            "status": "completed",
            "html": html,
            "comps": comps,
            "session_id": local_id,
            "changes": [],
        }
        return {"id": local_id, "status": "completed", "offline": True, "comps": comps}

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
            document_html=html,
            approval_mode="ask_every_time" if body.review_mode else "approve_all",
        )
        polled = sd.poll_job(job_id)
    except SuperDocsError as e:
        raise HTTPException(502, str(e)) from e
    JOBS[job_id] = {
        "mode": "live",
        "session_id": session_id,
        "job": polled,
        "comps": comps,
        "html": _html_from_job(polled),
    }
    return _job_out(job_id)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "job not found")
    rec = JOBS[job_id]
    if rec["mode"] == "live":
        rec["job"] = SuperDocs().get_job(job_id)
        rec["html"] = _html_from_job(rec["job"]) or rec.get("html")
    return _job_out(job_id)


@app.post("/jobs/{job_id}/review")
def review(job_id: str, body: DecisionIn):
    rec = JOBS.get(job_id)
    if not rec:
        raise HTTPException(404, "job not found")
    if rec["mode"] != "live":
        rec["status"] = "completed"
        return _job_out(job_id)
    sd = SuperDocs()
    job = rec["job"]
    kind = (job.get("metadata") or {}).get("awaiting_kind")
    session_id = rec["session_id"]
    try:
        if kind == "continue_prompt":
            sd.continue_job(session_id, job_id, True)
        else:
            sd.approve(session_id, job_id, body.decisions)
        rec["job"] = sd.poll_job(job_id)
        rec["html"] = _html_from_job(rec["job"]) or rec.get("html")
    except SuperDocsError as e:
        raise HTTPException(502, str(e)) from e
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
    if rec["mode"] == "offline":
        return {
            "id": job_id,
            "status": rec["status"],
            "offline": True,
            "comps": rec["comps"],
            "html": rec["html"],
            "changes": [],
            "awaiting_kind": None,
        }
    job = rec["job"]
    changes = parse_pending_changes(job)
    return {
        "id": job_id,
        "status": job.get("status"),
        "offline": False,
        "comps": rec["comps"],
        "html": rec.get("html"),
        "changes": changes,
        "awaiting_kind": (job.get("metadata") or {}).get("awaiting_kind"),
        "error": job.get("error"),
    }
