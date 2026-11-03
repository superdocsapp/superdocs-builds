"""
HTTP API for the Case Status & Document Checklist Letter Desk.

Run locally:
    uvicorn case_status_desk.app:app --reload

Deployed on Render via render.yaml (see repo root). Endpoints require a
staff API key (see auth.py) since case data is PII.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import service
from .auth import require_staff_user, require_approver, StaffUser
from .case_import import CsvFileCaseSource, XlsxFileCaseSource, sync_cases
from .cases import case_from_db_record
from .db import CaseRecord, GeneratedLetter, get_session, init_db
from .logging_setup import configure_logging, new_request_id, request_id_var
from .rate_limit import RateLimitMiddleware
from .superdocs_client import SuperDocsClient, SuperDocsAuthError, SuperDocsError, SuperDocsTransientError

configure_logging()
logger = logging.getLogger("case_status_desk.app")

app = FastAPI(title="Case Status & Document Checklist Letter Desk", version="1.0.0")
app.add_middleware(RateLimitMiddleware)


@app.middleware("http")
async def add_request_id_and_log(request: Request, call_next):
    rid = new_request_id()
    request.state.request_id = rid
    request_id_var.set(rid)  # best-effort; also stamped explicitly below since
                              # contextvars don't reliably cross BaseHTTPMiddleware's
                              # internal task boundary in Starlette
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled exception",
                          extra={"path": request.url.path, "method": request.method, "request_id": rid})
        raise
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    logger.info(
        "request_handled",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "request_id": rid,
        },
    )
    response.headers["X-Request-ID"] = rid
    return response


@app.on_event("startup")  # noqa: deprecated but stable; fine for this app's size
def on_startup() -> None:
    init_db()


def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def get_superdocs_client() -> SuperDocsClient:
    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Server misconfigured: SUPERDOCS_API_KEY not set")
    return SuperDocsClient(api_key=api_key)


# --- schemas -----------------------------------------------------------------

class DocumentOut(BaseModel):
    name: str
    form_type: str
    received: bool
    due_date: Optional[str] = None


class CaseOut(BaseModel):
    case_id: str
    client_name: str
    case_type: str
    stage: str
    stage_summary: str
    stage_next_step: str
    language: str
    fully_documented: bool
    outstanding_documents: list[DocumentOut]


class LetterOut(BaseModel):
    id: int
    case_id: str
    status: str
    stage_snapshot: str
    requested_by: str
    approved_by: Optional[str] = None
    superdocs_document_id: Optional[str] = None
    superdocs_document_title: Optional[str] = None
    validation_passed: Optional[bool] = None
    validation_issues: list[dict] = []
    validation_overridden_by: Optional[str] = None


# --- health --------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# --- cases ------------------------------------------------------------------

@app.get("/v1/cases", response_model=list[CaseOut])
def list_cases(
    needs_update: Optional[bool] = Query(None, description="Filter to cases with outstanding items"),
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_staff_user),
):
    records = db.query(CaseRecord).all()
    out = []
    for r in records:
        c = case_from_db_record(r)
        if needs_update is not None and c.is_fully_documented() == needs_update:
            continue
        out.append(_case_to_out(c))
    return out


@app.get("/v1/cases/{case_id}", response_model=CaseOut)
def get_case(case_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_staff_user)):
    record = db.get(CaseRecord, case_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id!r}")
    return _case_to_out(case_from_db_record(record))


def _case_to_out(c) -> CaseOut:
    return CaseOut(
        case_id=c.case_id,
        client_name=c.client_name,
        case_type=c.case_type,
        stage=c.stage,
        stage_summary=c.stage_summary,
        stage_next_step=c.stage_next_step,
        language=c.language,
        fully_documented=c.is_fully_documented(),
        outstanding_documents=[
            DocumentOut(name=d.name, form_type=d.form_type, received=d.received,
                        due_date=d.due_date.isoformat() if d.due_date else None)
            for d in c.required_documents
        ],
    )


# --- case data import: CMS via file upload -----------------------------------

class ImportResultOut(BaseModel):
    synced_count: int
    source_format: str
    filename: str


@app.post("/v1/cases/import-upload", response_model=ImportResultOut)
async def import_cases_upload(
    file: UploadFile = File(..., description="CSV or Excel (.xlsx) case export from the firm's CMS"),
    sheet_name: Optional[str] = Form(None, description="Excel only: sheet to read, defaults to the active sheet"),
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_staff_user),
):
    """Upload a case-data export (CSV or .xlsx) from whatever CMS the firm
    actually uses and sync it into the case store.

    This sidesteps needing a live, vendor-specific CMS integration: every
    practice-management system can export its case list to CSV or Excel,
    so instead of building and maintaining a bespoke API adapter per CMS,
    the firm exports periodically and uploads the file here. Column shape
    is documented in case_import.CsvFileCaseSource; extra columns are
    ignored, and rows missing a case_id are skipped rather than failing
    the whole import.

    Upserts by case_id -- safe to re-run on every export, and this is
    exactly what keeps 'outstanding checklist reflects the true current
    state of the file' true after a re-upload, not just after the first one.
    """
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in (".csv", ".xlsx"):
        raise HTTPException(status_code=415, detail=f"Unsupported file type {suffix!r}. Use .csv or .xlsx.")

    contents = await file.read()
    tmp_dir = Path(tempfile.mkdtemp(prefix="case-import-"))
    tmp_path = tmp_dir / filename
    tmp_path.write_bytes(contents)

    try:
        if suffix == ".csv":
            source = CsvFileCaseSource(tmp_path)
        else:
            source = XlsxFileCaseSource(tmp_path, sheet_name=sheet_name)
        try:
            count = sync_cases(source, get_session)
        except (ValueError, ImportError) as e:
            raise HTTPException(status_code=422, detail=str(e))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass

    logger.info("case_import_upload", extra={"import_filename": filename, "synced_count": count,
                                              "requested_by": staff.name})
    return ImportResultOut(synced_count=count, source_format=suffix.lstrip("."), filename=filename)




@app.post("/v1/cases/{case_id}/letters", response_model=LetterOut)
def draft_letter(
    case_id: str,
    block_on_validation_error: bool = False,
    db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_staff_user),
    client: SuperDocsClient = Depends(get_superdocs_client),
):
    try:
        letter = service.draft_letter(db, client, case_id, requested_by=staff.name,
                                       block_on_validation_error=block_on_validation_error)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.ValidationFailedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except SuperDocsAuthError as e:
        raise HTTPException(status_code=502, detail=f"SuperDocs credential rejected: {e}")
    except SuperDocsTransientError as e:
        raise HTTPException(status_code=503, detail=f"SuperDocs temporarily unavailable: {e}")
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return _letter_to_out(letter)


@app.post("/v1/letters/{letter_id}/approve", response_model=LetterOut)
def approve_letter(letter_id: int, override_validation: bool = False,
                    db: Session = Depends(get_db), staff: StaffUser = Depends(require_approver)):
    try:
        letter = service.approve_letter(db, letter_id, approved_by=staff.name,
                                         override_validation=override_validation)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.SelfApprovalError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except service.ValidationFailedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _letter_to_out(letter)


@app.post("/v1/letters/{letter_id}/export")
def export_letter(
    letter_id: int,
    db: Session = Depends(get_db),
    _staff: StaffUser = Depends(require_approver),
    client: SuperDocsClient = Depends(get_superdocs_client),
):
    try:
        path = service.export_letter(db, client, letter_id)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.ApprovalRequiredError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return FileResponse(path, filename=path.name,
                         media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.post("/v1/letters/{letter_id}/archive-superdocs-document")
def archive_letter_superdocs_document(
    letter_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    _staff: StaffUser = Depends(require_approver),
    client: SuperDocsClient = Depends(get_superdocs_client),
):
    """Archive (soft-delete) the SuperDocs durable File linked to this
    letter, e.g. once a case closes. No-op if no File was linked."""
    try:
        service.archive_letter_document(db, client, letter_id, force=force)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "ok"}


def _letter_to_out(letter: GeneratedLetter) -> LetterOut:
    issues = json.loads(letter.validation_issues) if letter.validation_issues else []
    return LetterOut(
        id=letter.id, case_id=letter.case_id, status=letter.status,
        stage_snapshot=letter.stage_snapshot, requested_by=letter.requested_by,
        approved_by=letter.approved_by,
        superdocs_document_id=letter.superdocs_document_id,
        superdocs_document_title=letter.superdocs_document_title,
        validation_passed=letter.validation_passed,
        validation_issues=issues,
        validation_overridden_by=letter.validation_overridden_by,
    )
