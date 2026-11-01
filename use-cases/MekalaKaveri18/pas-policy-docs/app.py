from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "_lib"))
sys.path.insert(0, str(ROOT))

from fill import TEMPLATE, fill_template, instruction, pas_items  # noqa: E402
from gate import items_to_queue, preview_html, record_decision  # noqa: E402
from superdocs import SuperDocs, SuperDocsError, load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")

app = FastAPI(title="PAS policy document")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
JOBS: dict[str, dict] = {}
SAMPLE = json.loads((ROOT / "fixtures" / "sample-policy.json").read_text(encoding="utf-8"))


class GenerateIn(BaseModel):
    policy: dict = Field(default_factory=dict)
    review_mode: bool = True
    sample: bool = False


class DecisionIn(BaseModel):
    decisions: dict[str, bool] = Field(default_factory=dict)


@app.get("/")
def index():
    return HTMLResponse((ROOT / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
def health():
    return {"ok": True, "superdocs": SuperDocs().enabled()}


@app.get("/sample")
def sample():
    return SAMPLE


@app.post("/jobs")
def start(body: GenerateIn):
    payload = body.policy or SAMPLE
    items = pas_items(payload)
    if body.review_mode or body.sample or not SuperDocs().enabled():
        local_id = f"local-{uuid.uuid4()}"
        if not body.review_mode:
            filled = preview_html(TEMPLATE, items, {c["change_id"]: True for c in items})
            JOBS[local_id] = {
                "mode": "offline",
                "status": "completed",
                "html": filled,
                "baseline_html": TEMPLATE,
                "payload": payload,
                "session_id": local_id,
                "changes": [],
                "queue": items,
                "applied": True,
                "register": [{"change_id": c["change_id"], "label": c["ai_explanation"], "decision": True} for c in items],
            }
            return _out(local_id)
        rec = items_to_queue(items)
        rec["baseline_html"] = TEMPLATE
        rec["html"] = TEMPLATE
        rec["payload"] = payload
        rec["session_id"] = local_id
        JOBS[local_id] = rec
        return _out(local_id)
    sd = SuperDocs()
    session_id = f"pas-{uuid.uuid4()}"
    filled = preview_html(TEMPLATE, items, {c["change_id"]: True for c in items})
    try:
        try:
            sd.upload_template("endorsement-template.html", TEMPLATE.encode("utf-8"), "text/html")
        except SuperDocsError:
            pass
        job_id = sd.chat_async(
            session_id,
            instruction(payload),
            document_html=filled,
            approval_mode="approve_all",
        )
        polled = sd.poll_job(job_id)
    except SuperDocsError as e:
        raise HTTPException(502, str(e)) from e
    JOBS[job_id] = {
        "mode": "live",
        "session_id": session_id,
        "job": polled,
        "html": _html(polled) or filled,
        "payload": payload,
        "changes": [],
        "status": polled.get("status"),
        "applied": True,
    }
    return _out(job_id)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "job not found")
    return _out(job_id)


@app.post("/jobs/{job_id}/review")
def review(job_id: str, body: DecisionIn):
    rec = JOBS.get(job_id)
    if not rec:
        raise HTTPException(404, "job not found")
    record_decision(rec, body.decisions)
    return _out(job_id)


@app.get("/jobs/{job_id}/export")
def export(job_id: str, fmt: str = "docx"):
    rec = JOBS.get(job_id)
    if not rec:
        raise HTTPException(404, "job not found")
    html = rec.get("html") or ""
    sd = SuperDocs()
    if rec["mode"] == "live" and sd.enabled():
        data = sd.export(session_id=rec["session_id"], html=html, fmt=fmt, filename="policy-endorsement")
        return Response(data, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename=policy-endorsement.{fmt}"})
    path = ROOT / "exports"
    path.mkdir(exist_ok=True)
    out = path / f"policy-{job_id[:8]}.html"
    out.write_text(html, encoding="utf-8")
    return FileResponse(out, filename="policy-endorsement.html")


def _html(job: dict) -> str:
    result = job.get("result") or {}
    changes = result.get("document_changes") or {}
    return changes.get("updated_html") or ""


def _out(job_id: str) -> dict:
    rec = JOBS[job_id]
    return {
        "id": job_id,
        "status": rec.get("status") or (rec.get("job") or {}).get("status"),
        "offline": rec.get("mode") != "live",
        "html": rec.get("html"),
        "changes": rec.get("changes") or [],
        "register": rec.get("register") or [],
        "payload": rec.get("payload"),
        "applied": rec.get("applied"),
        "error": (rec.get("job") or {}).get("error") if rec.get("job") else None,
    }
