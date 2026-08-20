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
from spine import BIBLE, MANUSCRIPT, find_breaks, hashes, instruction, offline_repair  # noqa: E402
from superdocs import SuperDocs, load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")
app = FastAPI(title="Plot spine")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
JOBS: dict = {}


class StartIn(BaseModel):
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


@app.get("/bible")
def bible():
    return BIBLE


@app.post("/breaks")
def breaks():
    b = find_breaks(MANUSCRIPT)
    return {"breaks": b, "before": hashes(MANUSCRIPT)}


@app.post("/jobs")
def start(body: StartIn):
    issues = find_breaks(MANUSCRIPT)
    before = hashes(MANUSCRIPT)
    html = offline_repair(MANUSCRIPT) if body.sample or not SuperDocs().enabled() else MANUSCRIPT
    extra = {"breaks": issues, "before": before, "after": hashes(html)}
    result = start_job(
        html=html,
        message=instruction(issues),
        template_name="novel-spine.html",
        template_bytes=MANUSCRIPT.encode("utf-8"),
        prefix="spine",
        extra=extra,
        review_mode=body.review_mode,
        force_offline=body.sample,
        jobs=JOBS,
    )
    rec = JOBS[result["id"]]
    rec["after"] = hashes(rec.get("html") or html)
    result["after"] = rec["after"]
    result["unchanged"] = {
        cid: rec["after"].get(cid) == before.get(cid) for cid in before if cid != "chapter-12"
    }
    return result


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    return refresh(JOBS, job_id)


@app.post("/jobs/{job_id}/review")
def decide(job_id: str, body: DecisionIn):
    return review(JOBS, job_id, body.decisions)


@app.get("/jobs/{job_id}/export")
def export(job_id: str):
    return export_job(JOBS, job_id, "salt-on-the-northern-quay", ROOT / "exports")
