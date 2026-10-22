from __future__ import annotations

import base64
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..core import boundary
from ..core.negotiation import NegotiationError, NegotiationService
from ..core.store import DealRow, DocumentRow, ProposalRow
from ..superdocs.transport import SuperDocsAPIError

router = APIRouter()

CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def get_service(request: Request) -> NegotiationService:
    return request.app.state.service


ServiceDep = Annotated[NegotiationService, Depends(get_service)]


def _deal_dict(deal: DealRow) -> dict[str, Any]:
    return {
        "deal_id": deal.id,
        "name": deal.name,
        "superdocs_session_id": deal.superdocs_session_id,
        "approval_policy": deal.approval_policy,
        "current_version": deal.current_version,
        "status": deal.status,
    }


def _document_dict(document: DocumentRow) -> dict[str, Any]:
    return {
        "id": document.id,
        "deal_id": document.deal_id,
        "superdocs_document_id": document.superdocs_document_id,
        "filename": document.filename,
        "role": document.role,
        "added_by_side": document.added_by_side,
        "created_at": document.created_at,
    }


def _proposal_dict(p: ProposalRow) -> dict[str, Any]:
    return {
        "id": p.id,
        "job_id": p.job_id,
        "change_id": p.change_id,
        "operation": p.operation,
        "old_html": p.old_html,
        "new_html": p.new_html,
        "ai_explanation": p.ai_explanation,
        "proposed_by_side": p.proposed_by_side,
        "vendor_decision": p.vendor_decision,
        "customer_decision": p.customer_decision,
        "state": p.state,
    }


class StartDealRequest(BaseModel):
    name: str
    side: str
    user: str
    filename: str
    file_base64: str
    approval_policy: str | None = None


@router.post("/deals")
async def create_deal(payload: StartDealRequest, service: ServiceDep) -> dict[str, Any]:
    try:
        content = base64.b64decode(payload.file_base64)
    except Exception as exc:
        raise HTTPException(422, f"file_base64 could not be decoded: {exc}") from exc
    try:
        deal = await service.start_deal(
            name=payload.name,
            started_by_side=payload.side,
            started_by_user=payload.user,
            filename=payload.filename,
            file_bytes=content,
            approval_policy=payload.approval_policy,
        )
    except NegotiationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SuperDocsAPIError as exc:
        raise HTTPException(502, f"SuperDocs upload failed: {exc.message}") from exc
    return _deal_dict(deal)


@router.post("/deals/upload")
async def create_deal_multipart(
    service: ServiceDep,
    name: Annotated[str, Form()],
    side: Annotated[str, Form()],
    user: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    approval_policy: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Streaming-friendly alternative to POST /deals.

    The JSON endpoint requires the caller to base64 the whole file into a string, which
    inflates it by ~33% and forces the entire document through memory twice. Real
    contracts arrive as multipart uploads, so this path reads the file in chunks and
    hands the bytes straight to SuperDocs.
    """
    content = await _read_upload(file)
    try:
        deal = await service.start_deal(
            name=name,
            started_by_side=side,
            started_by_user=user,
            filename=file.filename or "document.docx",
            file_bytes=content,
            approval_policy=approval_policy,
        )
    except NegotiationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SuperDocsAPIError as exc:
        raise HTTPException(502, f"SuperDocs upload failed: {exc.message}") from exc
    return _deal_dict(deal)


async def _read_upload(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413,
                f"file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit; "
                "split the document or raise MAX_UPLOAD_BYTES",
            )
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(422, "uploaded file was empty")
    return b"".join(chunks)


@router.post("/deals/{deal_id}/documents")
async def add_document(
    deal_id: str,
    service: ServiceDep,
    side: Annotated[str, Form()],
    user: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    role: Annotated[str, Form()] = "supporting",
) -> dict[str, Any]:
    content = await _read_upload(file)
    try:
        document = await service.add_document(
            deal_id,
            side,
            user,
            file.filename or "document.docx",
            content,
            role=role,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except boundary.BoundaryViolation as exc:
        raise HTTPException(403, str(exc)) from exc
    except SuperDocsAPIError as exc:
        raise HTTPException(502, f"SuperDocs error: {exc.message}") from exc
    return _document_dict(document)


@router.get("/deals/{deal_id}/documents")
async def list_documents(deal_id: str, service: ServiceDep) -> dict[str, Any]:
    try:
        service.store.get_deal(deal_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"documents": [_document_dict(d) for d in service.list_documents(deal_id)]}


@router.get("/deals/{deal_id}/search")
async def search(
    deal_id: str,
    service: ServiceDep,
    q: str,
    side: str,
    source_channel_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    try:
        hits = service.search(
            deal_id, q, source_channel_id=source_channel_id, side=side, limit=limit
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "query": q,
        "hits": [
            {
                "kind": hit.kind,
                "label": hit.label,
                "snippet": hit.snippet,
                "audience": hit.audience,
                "proposal_id": hit.proposal_id,
            }
            for hit in hits
        ],
    }


class ProposeRequest(BaseModel):
    side: str
    user: str
    instruction: str
    source_channel_id: str
    document_id: str | None = None
    # Optional. Omit it and one is derived from (deal, document, instruction), which is
    # enough to stop a retried call buying a second SuperDocs operation. Supply your own
    # when the caller wants to define what "the same request" means.
    idempotency_key: str | None = None


@router.post("/deals/{deal_id}/propose")
async def propose(deal_id: str, payload: ProposeRequest, service: ServiceDep) -> dict[str, Any]:
    try:
        job = await service.propose(
            deal_id,
            payload.side,
            payload.user,
            payload.instruction,
            payload.source_channel_id,
            document_id=payload.document_id,
            idempotency_key=payload.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except NegotiationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except boundary.BoundaryViolation as exc:
        raise HTTPException(403, str(exc)) from exc
    except SuperDocsAPIError as exc:
        raise HTTPException(502, f"SuperDocs error: {exc.message}") from exc
    job = await service.drive_job(job.job_id)
    proposals = service.store.proposals_for_job(job.job_id)
    return {
        "job_id": job.job_id,
        "state": job.state,
        "proposals": [_proposal_dict(p) for p in proposals],
    }


class DecideRequest(BaseModel):
    side: str
    user: str
    approved: bool
    feedback: str | None = None


@router.post("/deals/{deal_id}/proposals/{proposal_id}/decide")
async def decide(
    deal_id: str, proposal_id: str, payload: DecideRequest, service: ServiceDep
) -> dict[str, Any]:
    try:
        proposal = await service.decide(
            deal_id, proposal_id, payload.side, payload.user, payload.approved, payload.feedback
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except NegotiationError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SuperDocsAPIError as exc:
        raise HTTPException(502, f"SuperDocs error: {exc.message}") from exc
    return _proposal_dict(proposal)


@router.get("/deals/{deal_id}/status")
async def status(deal_id: str, service: ServiceDep) -> dict[str, Any]:
    try:
        return service.status(deal_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/deals/{deal_id}/history")
async def history(deal_id: str, service: ServiceDep) -> dict[str, Any]:
    try:
        return {"lines": service.history_lines(deal_id)}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


class ExportRequest(BaseModel):
    kind: str


@router.post("/deals/{deal_id}/export")
async def export(deal_id: str, payload: ExportRequest, service: ServiceDep) -> dict[str, Any]:
    if payload.kind not in ("clean", "redline"):
        raise HTTPException(422, "kind must be 'clean' or 'redline'")
    try:
        exported = (
            await service.export_clean(deal_id)
            if payload.kind == "clean"
            else await service.export_redline(deal_id)
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except SuperDocsAPIError as exc:
        raise HTTPException(502, f"SuperDocs error: {exc.message}") from exc
    return {
        "filename": exported.filename,
        "content_base64": base64.b64encode(exported.content).decode("ascii"),
    }


class NoteRequest(BaseModel):
    side: str
    author: str
    body: str


@router.post("/deals/{deal_id}/notes")
async def add_note(deal_id: str, payload: NoteRequest, service: ServiceDep) -> dict[str, Any]:
    try:
        await service.add_internal_note(deal_id, payload.side, payload.author, payload.body)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}
