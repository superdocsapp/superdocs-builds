"""FastAPI APIRouter for Build B: FinOps ROI Calculator."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .calculator import CalculatorInputs, ReportGenerator, compute_tco

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Build B: FinOps ROI"])


class ExportReportRequest(BaseModel):
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,128}$")
    volume: int = Field(ge=1, le=1_000_000)
    hours: float = Field(ge=0, le=100_000)
    hourly_cost: float = Field(ge=0, le=10_000)
    infrastructure_monthly: float = Field(default=100.0, ge=0, le=50_000)
    horizon_years: int = Field(default=3, ge=1, le=10)


class ExportReportResponse(BaseModel):
    pdf_path: str
    html_length: int
    html: str
    pdf_data_url: str


@router.post("/export-report", response_model=ExportReportResponse)
async def export_report(req: ExportReportRequest) -> ExportReportResponse:
    """Generate ROI report via SuperDocs and export as PDF."""
    try:
        inputs = CalculatorInputs(
            volume=req.volume,
            hours=req.hours,
            hourly_cost=req.hourly_cost,
            infrastructure_monthly=req.infrastructure_monthly,
            horizon_years=req.horizon_years,
        )
        results = compute_tco(inputs)

        # Import SuperDocsClient dynamically
        try:
            from build_a.client import SuperDocsClient, SuperDocsError
        except ImportError:
            from client import SuperDocsClient, SuperDocsError

        async with SuperDocsClient() as client:
            gen = ReportGenerator(client)
            html = await gen.generate_report(req.session_id, results)
            reports_dir = Path("reports").resolve()
            reports_dir.mkdir(exist_ok=True)
            pdf_path = reports_dir / f"{req.session_id}.pdf"
            path = await gen.export_report(req.session_id, pdf_path)
            pdf_bytes = path.read_bytes() if path.exists() else b""
            pdf_b64 = base64.b64encode(pdf_bytes).decode() if pdf_bytes else ""
            pdf_data_url = f"data:application/pdf;base64,{pdf_b64}" if pdf_b64 else ""
            return ExportReportResponse(
                pdf_path=str(path),
                html_length=len(html),
                html=html,
                pdf_data_url=pdf_data_url,
            )
    except Exception as e:
        logger.exception("Failed to export ROI report: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
