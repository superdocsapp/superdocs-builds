"""Analysis dashboard: per-partner extracted facts, eligibility, citations."""

from __future__ import annotations

from fastapi import APIRouter

from app.backend.case_view import to_case_summary
from app.backend.lookups import get_run_or_404
from app.backend.schemas import CaseSummaryOut

router = APIRouter()


@router.get("/runs/{run_id}/cases", response_model=list[CaseSummaryOut])
async def list_cases(run_id: str):
    run = get_run_or_404(run_id)
    return [to_case_summary(c) for c in run.cases.values()]


@router.get("/runs/{run_id}/cases/{case_id}", response_model=CaseSummaryOut)
async def get_case(run_id: str, case_id: str):
    from app.backend.lookups import get_case_or_404

    run = get_run_or_404(run_id)
    case = get_case_or_404(run, case_id)
    return to_case_summary(case)
