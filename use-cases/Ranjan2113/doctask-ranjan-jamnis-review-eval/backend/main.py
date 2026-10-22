"""FastAPI backend for the reviewer study.

Deliberately thin. It serves condition-assigned batches to the reviewer UI and
records decision events with timestamps. It does not score anything, does not
know whether a decision was right, and never sends a ground-truth label over
the wire (GROUND_TRUTH_SAFETY.md GT-1, GT-6).

No auth, single researcher-run instance, per PLAN.md.pdf section 1's scope cuts.

Run:  uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.assignment import (  # noqa: E402
    CONDITIONS,
    Cell,
    assignments_to_dict,
    build_assignments,
    check_balance,
)
from backend.store import StudyStore  # noqa: E402
from ground_truth import make_decision_event  # noqa: E402

app = FastAPI(title="SuperDocs review-cost study", version="0.1.0")

# The UI is served from a dev server on another port; this is a single-user
# research tool on localhost, not a public service.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = StudyStore()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StartSessionRequest(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=64)


class DecisionRequest(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=64)
    batch_id: str
    condition: str
    reviewer_change_id: str
    decision: str
    shown_at: str
    decided_at: str
    # When the reviewer actually reached this change. Optional so an older
    # client still records, falling back to shown_at (PROGRESS.md A18).
    engaged_at: str | None = None
    note: str = ""


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "batches": store.batch_ids,
        "excluded_batches": store.excluded_batch_ids,
        "conditions": list(CONDITIONS),
        "events_recorded": len(store.read_events()),
    }


@app.get("/api/conditions")
def conditions() -> dict[str, Any]:
    return {"conditions": list(CONDITIONS)}


@app.post("/api/session/start")
def start_session(request: StartSessionRequest) -> dict[str, Any]:
    """Return this reviewer's counterbalanced running order.

    Assignments are persisted on first use and reused thereafter, so a reviewer
    who reloads mid-session resumes the same order rather than being
    re-randomised into a different one.
    """
    if not store.batch_ids:
        raise HTTPException(503, "no batches loaded; run corpus_builder.py first")

    assignment = store.load_assignment()
    reviewers = assignment.get("reviewers", {})

    if request.reviewer_id not in reviewers:
        known = sorted(reviewers) + [request.reviewer_id]
        cells = build_assignments(
            known,
            store.batch_ids,
            allow_partial=len(store.batch_ids) < len(CONDITIONS),
        )
        assignment = assignments_to_dict(cells)
        assignment["generated_at"] = now_iso()
        store.save_assignment(assignment)
        reviewers = assignment["reviewers"]

    return {
        "reviewer_id": request.reviewer_id,
        "assignment": reviewers[request.reviewer_id],
        "partial": len(store.batch_ids) < len(CONDITIONS),
    }


@app.get("/api/batch/{batch_id}")
def get_batch(batch_id: str, condition: str = "batch_section") -> dict[str, Any]:
    """Reviewer-facing batch content. Never carries ground truth (GT-1)."""
    if condition not in CONDITIONS:
        raise HTTPException(400, f"unknown condition {condition!r}")

    view = store.reviewer_view(batch_id)
    if view is None:
        raise HTTPException(404, f"unknown batch {batch_id!r}")

    presentation, granularity = condition.split("_", 1)
    return {
        **view,
        "condition": condition,
        "presentation": presentation,   # batch | sequential
        "granularity": granularity,     # section | whole
    }


@app.post("/api/decision")
def record_decision(request: DecisionRequest) -> dict[str, Any]:
    """Append one decision event (GT-6: no correctness stored)."""
    if request.condition not in CONDITIONS:
        raise HTTPException(400, f"unknown condition {request.condition!r}")

    valid_ids = store.change_ids_for(request.batch_id)
    if not valid_ids:
        raise HTTPException(404, f"unknown batch {request.batch_id!r}")
    if request.reviewer_change_id not in valid_ids:
        # Reject unknown ids rather than storing them: an event that joins to
        # nothing at analysis time is silently dropped from the results, which
        # would understate how many decisions a reviewer actually made.
        raise HTTPException(
            400, f"change {request.reviewer_change_id!r} is not in batch {request.batch_id!r}"
        )

    try:
        event = make_decision_event(
            reviewer_id=request.reviewer_id,
            batch_id=request.batch_id,
            condition=request.condition,
            reviewer_change_id=request.reviewer_change_id,
            decision=request.decision,
            shown_at=request.shown_at,
            engaged_at=request.engaged_at,
            decided_at=request.decided_at,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    event["recorded_at"] = now_iso()
    store.append_event(event)
    return {"ok": True, "decision_ms": event["decision_ms"]}


@app.get("/api/events/count")
def event_count(reviewer_id: str | None = None) -> dict[str, Any]:
    events = store.read_events()
    if reviewer_id:
        events = [e for e in events if e.get("reviewer_id") == reviewer_id]
    return {"count": len(events)}


@app.get("/api/assignment")
def get_assignment() -> dict[str, Any]:
    assignment = store.load_assignment()
    if not assignment:
        return {"reviewers": {}, "balance": {}}
    cells = [
        Cell(
            reviewer_id=reviewer_id,
            position=entry["position"],
            condition=entry["condition"],
            batch_id=entry["batch_id"],
        )
        for reviewer_id, entries in assignment.get("reviewers", {}).items()
        for entry in entries
    ]
    return {**assignment, "balance": check_balance(cells)}
