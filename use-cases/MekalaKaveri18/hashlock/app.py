from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "_lib"))
sys.path.insert(0, str(ROOT))

from jobs import export_job, refresh, review, start_job  # noqa: E402
from lock import SOURCE, instruction, offline_tighten, proof, tamper_locked  # noqa: E402
from superdocs import SuperDocs, load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")
app = FastAPI(title="Hashlock")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
JOBS: dict = {}


class StartIn(BaseModel):
    review_mode: bool = True
    sample: bool = False
    tamper: bool = False


class DecisionIn(BaseModel):
    decisions: dict[str, bool] = Field(default_factory=dict)


@app.get("/")
def index():
    return HTMLResponse((ROOT / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
def health():
    return {"ok": True, "superdocs": SuperDocs().enabled()}


@app.get("/source")
def source():
    return {"html": SOURCE, "before": proof(SOURCE, SOURCE)}


@app.post("/jobs")
def start(body: StartIn):
    html = SOURCE
    force_offline = body.sample or body.tamper or not SuperDocs().enabled()
    if force_offline:
        html = tamper_locked(SOURCE) if body.tamper else offline_tighten(SOURCE)
    extra = {"receipt": proof(SOURCE, html), "tamper": body.tamper}
    result = start_job(
        html=html,
        message=instruction(),
        template_name="msa-excerpt.html",
        template_bytes=SOURCE.encode("utf-8"),
        prefix="hashlock",
        extra=extra,
        review_mode=body.review_mode,
        force_offline=force_offline,
        jobs=JOBS,
    )
    rec = JOBS[result["id"]]
    after = rec.get("html") or html
    rec["receipt"] = proof(SOURCE, after)
    result["receipt"] = rec["receipt"]
    result["html"] = after
    return result


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    result = refresh(JOBS, job_id)
    rec = JOBS[job_id]
    rec["receipt"] = proof(SOURCE, rec.get("html") or SOURCE)
    result["receipt"] = rec["receipt"]
    return result


@app.post("/jobs/{job_id}/review")
def decide(job_id: str, body: DecisionIn):
    result = review(JOBS, job_id, body.decisions)
    rec = JOBS[job_id]
    rec["receipt"] = proof(SOURCE, rec.get("html") or SOURCE)
    result["receipt"] = rec["receipt"]
    return result


@app.get("/jobs/{job_id}/export")
def export(job_id: str):
    return export_job(JOBS, job_id, "hashlock-msa", ROOT / "exports")
