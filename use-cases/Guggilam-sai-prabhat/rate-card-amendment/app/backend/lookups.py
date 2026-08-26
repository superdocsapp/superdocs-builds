"""Shared run/case lookup helpers that raise structured 404s."""

from __future__ import annotations

from fastapi import HTTPException

from app.backend.store import Run, store
from src.amendment_case import AmendmentCase


def get_run_or_404(run_id: str) -> Run:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={
                "what": f"run '{run_id}' was not found",
                "likely_cause": "the run_id is wrong, or the server restarted (runs are in-memory, not persisted across restarts)",
                "next_action": "resubmit the intake form to start a new run",
            },
        )
    return run


def get_case_or_404(run: Run, case_id: str) -> AmendmentCase:
    case = run.cases.get(case_id)
    if case is None:
        raise HTTPException(
            status_code=404,
            detail={
                "what": f"case '{case_id}' was not found in run '{run.run_id}'",
                "likely_cause": "the case_id is wrong or belongs to a different run",
                "next_action": "re-fetch GET /runs/{run_id}/cases for the correct case_id list",
            },
        )
    return case
