"""HTTP surface for the Sheets add-on.

Three verbs, matching how the add-on actually works: ask what the report *would*
say, look at it, then accept or reject it section by section. Nothing here
writes a document without a decision arriving first.

The add-on calls this from Apps Script's server side (``UrlFetchApp``), not from
the sidebar's browser context, so there is no CORS story and the shared secret
never reaches the page.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from .facts import RangeParseError
from .incremental import UntouchedSectionChanged
from .pipeline import NarrativeReportPipeline
from .store import ReportStore
from .superdocs import QuotaExhausted, SuperDocsClient, SuperDocsError

log = logging.getLogger(__name__)

STORE_ROOT = pathlib.Path(os.environ.get("NARRATIVE_STORE", "./data/reports"))
ADDON_TOKEN = os.environ.get("NARRATIVE_ADDON_TOKEN")

EXPORT_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html",
    "markdown": "text/markdown",
    "txt": "text/plain",
}


# --------------------------------------------------------------------- models


class ProposeRequest(BaseModel):
    values: list[list[str]] = Field(..., description="The selected range, row-major, as strings")
    sheet: str = Field(..., description="Sheet name, used for provenance")
    a1: str = Field(..., description="A1 notation of the selection, e.g. B2:F14")
    report_id: str | None = Field(None, description="Omit to create a new report")
    title: str | None = None


class CommitRequest(BaseModel):
    decisions: dict[str, bool] = Field(..., description="section id -> accepted")
    format: str = Field("docx", description="docx, pdf, html, markdown or txt")


# ----------------------------------------------------------------- app wiring


def _locks() -> defaultdict[str, asyncio.Lock]:
    return defaultdict(asyncio.Lock)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """One client for the process; one lock per report."""
    app.state.store = ReportStore(STORE_ROOT)
    app.state.locks = _locks()
    app.state.client = SuperDocsClient()
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(
    title="Sheets narrative report",
    version="0.1.0",
    summary="Turn a spreadsheet range into a reviewed, firm-templated report.",
    lifespan=lifespan,
)


async def require_token(x_addon_token: str | None = Header(None)) -> None:
    """Shared secret between the add-on and this service.

    Left open when unset so a stranger can clone and run without configuring
    anything; the README is explicit that deploying without it is not an option.
    """
    if ADDON_TOKEN and x_addon_token != ADDON_TOKEN:
        raise HTTPException(status_code=401, detail="invalid or missing X-Addon-Token")


def pipeline_for(app: FastAPI) -> NarrativeReportPipeline:
    return NarrativeReportPipeline(app.state.client, app.state.store)


# ------------------------------------------------------------------- endpoints


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    """Liveness plus remaining quota, so the add-on can warn before it fails."""
    try:
        remaining = await app.state.client.remaining_operations()
    except SuperDocsError as exc:
        return {"status": "degraded", "detail": str(exc)}
    return {"status": "ok", "operations_remaining": remaining}


@app.get("/reports", dependencies=[Depends(require_token)])
async def list_reports() -> dict[str, list[str]]:
    return {"reports": app.state.store.list_reports()}


@app.post("/reports/propose", dependencies=[Depends(require_token)])
async def propose(request: ProposeRequest) -> dict[str, Any]:
    """Compute the report and stop for review. Writes nothing to the document."""
    report_id = request.report_id or ""
    async with app.state.locks[report_id or "new"]:
        try:
            report = await pipeline_for(app).propose(
                report_id=request.report_id,
                values=request.values,
                sheet=request.sheet,
                a1=request.a1,
                title=request.title,
            )
        except RangeParseError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "the selection could not be read",
                    "cause": str(exc),
                    "fix": "select a block with a header row of periods and a left column of labels",
                },
            ) from exc
        except QuotaExhausted as exc:
            raise HTTPException(status_code=429, detail={"error": str(exc)}) from exc
        except UntouchedSectionChanged as exc:
            # Refuse to show a proposal we cannot vouch for.
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "internal consistency check failed",
                    "cause": str(exc),
                    "fix": "this is a bug; the report was not modified",
                },
            ) from exc
        except SuperDocsError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
    return report.to_dict()


@app.post("/reports/{report_id}/commit", dependencies=[Depends(require_token)])
async def commit(report_id: str, request: CommitRequest) -> dict[str, Any]:
    """Apply the accepted sections and export."""
    if request.format not in EXPORT_MIME:
        raise HTTPException(
            status_code=422,
            detail={"error": f"unsupported format {request.format!r}",
                    "fix": f"use one of {', '.join(sorted(EXPORT_MIME))}"},
        )
    async with app.state.locks[report_id]:
        try:
            report, blob = await pipeline_for(app).commit(
                report_id, request.decisions, export_format=request.format
            )
        except SuperDocsError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc), "fix": exc.fix}) from exc

        if blob:
            path = app.state.store.manifest_path(report_id).parent / f"report.{request.format}"
            path.write_bytes(blob)

    payload = report.to_dict()
    payload["download"] = f"/reports/{report_id}/download?format={request.format}" if blob else None
    payload["exported_bytes"] = len(blob) if blob else 0
    return payload


@app.get("/reports/{report_id}/download", dependencies=[Depends(require_token)])
async def download(report_id: str, format: str = "docx") -> Response:
    """Serve the last export of this report."""
    if format not in EXPORT_MIME:
        raise HTTPException(status_code=422, detail=f"unsupported format {format!r}")
    path = app.state.store.manifest_path(report_id).parent / f"report.{format}"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "no export on disk for this report",
                    "fix": "commit the report first"},
        )
    return Response(
        content=path.read_bytes(),
        media_type=EXPORT_MIME[format],
        headers={"Content-Disposition": f'attachment; filename="{report_id}.{format}"'},
    )


@app.get("/reports/{report_id}", dependencies=[Depends(require_token)])
async def get_report(report_id: str) -> dict[str, Any]:
    """Current state: the committed manifest and any review left in flight."""
    manifest = app.state.store.load_manifest(report_id)
    pending = app.state.store.load_run(report_id)
    if manifest is None and pending is None:
        raise HTTPException(status_code=404, detail=f"unknown report {report_id!r}")
    return {
        "report_id": report_id,
        "revision": manifest.revision if manifest else 0,
        "source_range": manifest.source_range if manifest else None,
        "sections": [
            {"id": s.id, "heading": s.heading, "html": s.rendered}
            for s in (manifest.sections if manifest else [])
        ],
        "awaiting_review": pending is not None,
    }
