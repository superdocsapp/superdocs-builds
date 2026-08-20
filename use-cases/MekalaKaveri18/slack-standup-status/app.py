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
from memo import TEMPLATE, draft_memo, instruction, load_standup, search_playbook  # noqa: E402
from superdocs import SuperDocs, load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")
app = FastAPI(title="Slack standup → customer status")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
JOBS: dict = {}


class StartIn(BaseModel):
    query: str = "customer ciso date"
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


@app.get("/fixture")
def fixture():
    return load_standup()


@app.post("/search")
def search(body: dict):
    return {"hits": search_playbook(str(body.get("query") or ""))}


@app.post("/jobs")
def start(body: StartIn):
    payload = load_standup()
    rules = search_playbook(body.query)
    html = draft_memo(payload)
    return start_job(
        html=html,
        message=instruction(payload, rules),
        template_name="customer-status.html",
        template_bytes=TEMPLATE.encode("utf-8"),
        prefix="standup",
        extra={"playbook": rules},
        review_mode=body.review_mode,
        force_offline=body.sample,
        jobs=JOBS,
    )


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    return refresh(JOBS, job_id)


@app.post("/jobs/{job_id}/review")
def decide(job_id: str, body: DecisionIn):
    return review(JOBS, job_id, body.decisions)


@app.get("/jobs/{job_id}/export")
def export(job_id: str):
    return export_job(JOBS, job_id, "customer-status", ROOT / "exports")
