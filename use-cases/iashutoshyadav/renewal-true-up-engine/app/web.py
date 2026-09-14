"""Minimal review UI: run the cohort batch, see clean renewals vs. genuine exceptions, decide each
exception one at a time. In-memory state on purpose - this is a single-operator batch review tool for one
cohort run at a time, not a multi-user persistent system; the task card's actual scope (one renewals
manager reviewing one cohort) doesn't need a database, and adding one here would be exactly the kind of
unnecessary feature the brief asks us to skip.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.batch import BatchResult, run_cohort_batch
from app.renewal_engine import apply_human_decision
from app.superdocs_client import make_client
from data.sample_cohort.cohort import load_sample_cohort

# python-dotenv doesn't load .env into os.environ on its own - found live on 2026-08-19 when a real
# SUPERDOCS_API_KEY set in .env was silently ignored and the app kept running against the fake client
# with no error, only the (correctly rendered, but unhelpfully unnoticed) "offline fake client" banner
# as any signal. Must run before _get_client()/dashboard() ever read os.environ.
load_dotenv()

app = FastAPI(title="Renewal & True-Up Documentation Engine")
templates = Jinja2Templates(directory="app/templates")

_TEMPLATE_NAME = "renewal_amendment_template.txt"
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "data" / _TEMPLATE_NAME

_state: dict[str, object] = {"result": None, "client": None, "progress": None, "template_uploaded": False}


def _get_client():
    if _state["client"] is None:
        _state["client"] = make_client(os.environ.get("SUPERDOCS_API_KEY"))
    return _state["client"]


def _ensure_template_uploaded(client) -> str:
    """Templates persist at the account level across sessions (per docs.superdocs.app), so this only
    needs to happen once per process, not once per customer - re-uploading it for every renewal would be
    wasteful and would pile up duplicate template listings over repeated batch runs."""
    if not _state["template_uploaded"]:
        client.upload_template(_TEMPLATE_NAME, _TEMPLATE_PATH.read_bytes())
        _state["template_uploaded"] = True
    return _TEMPLATE_NAME


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    result: BatchResult | None = _state["result"]  # type: ignore[assignment]
    using_fake = os.environ.get("SUPERDOCS_API_KEY", "") == ""
    return templates.TemplateResponse(
        request, "dashboard.html", {"result": result, "using_fake": using_fake}
    )


@app.post("/batch/run")
def run_batch():
    # Real-time progress wasn't visible anywhere before this - a real batch against the live API takes
    # 20-90+ seconds (verified live, 2026-08-20), and the button just sat there with zero feedback the
    # whole time. run_cohort_batch already accepted an on_progress callback; it was just never passed.
    # Starlette runs this sync route in its thread pool, so a concurrent GET to /batch/progress (below)
    # is served by a different thread while this is still running - no background-task machinery needed.
    def on_progress(current: int, total: int, customer_id: str, status: str) -> None:
        _state["progress"] = {"current": current, "total": total, "customer_id": customer_id, "status": status}

    _state["progress"] = {"current": 0, "total": None, "customer_id": None, "status": "starting"}
    client = _get_client()
    template_name = _ensure_template_uploaded(client)
    items = load_sample_cohort()
    try:
        _state["result"] = run_cohort_batch(
            client, items, max_customers=50, on_progress=on_progress, template_name=template_name
        )
    finally:
        _state["progress"] = None
    return RedirectResponse(url="/", status_code=303)


@app.get("/batch/progress")
def batch_progress():
    return JSONResponse(_state["progress"])


@app.get("/review/{customer_id}", response_class=HTMLResponse)
def review_item(request: Request, customer_id: str):
    # Keyed by customer_id, not change_id: a clause_not_found exception has no change_id at all (nothing
    # was ever proposed to SuperDocs), so it needs a stable identifier every pending item actually has.
    result: BatchResult | None = _state["result"]  # type: ignore[assignment]
    item = next((p for p in (result.pending_review if result else []) if p.package.customer.customer_id == customer_id), None)
    if item is None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "review.html", {"item": item})


@app.get("/pack/{customer_id}", response_class=HTMLResponse)
def pack_item(request: Request, customer_id: str):
    result: BatchResult | None = _state["result"]  # type: ignore[assignment]
    package = next((p for p in (result.clean if result else []) if p.customer.customer_id == customer_id), None)
    if package is None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "pack.html", {"package": package})


@app.post("/review/{customer_id}/decide")
def decide_item(customer_id: str, approved: bool = Form(...), reason: str = Form(default="")):
    result: BatchResult = _state["result"]  # type: ignore[assignment]
    item = next(p for p in result.pending_review if p.package.customer.customer_id == customer_id)
    if item.change_id is not None:  # nothing to approve/reject for a clause_not_found item
        client = _get_client()
        apply_human_decision(client, item.package, item.job_id, item.change_id, approved=approved, reason=reason or None)
    result.pending_review = [p for p in result.pending_review if p.package.customer.customer_id != customer_id]
    result.clean.append(item.package)
    return RedirectResponse(url="/", status_code=303)
