from __future__ import annotations
from typing import Annotated, Any
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from series_bible.application.ingestion import IngestionService
from series_bible.config import Settings, get_settings
from series_bible.domain.schemas import ApprovalRequest, ProposedEditRequest, Resolution, ReviewRequest, SeriesCreate, SeriesView
from series_bible.infrastructure.database import AuditEvent, BibleFact, ContinuityFinding, Document, ProposedChange, ReviewDecision, Series, WorkflowRun, get_session
from series_bible.infrastructure.superdocs_service import ApproveChangeRequest, EditInstructionRequest, ExportDocumentRequest, ExportOptions, SuperDocsConnection, SuperDocsService, SuperDocsServiceError

router = APIRouter(prefix="/api/v1")
Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]

class RunCreate(BaseModel):
    document_ids: list[UUID] = Field(default_factory=list)

class ExportRequest(BaseModel):
    document_id: UUID
    format: str = "docx"
    filename: str | None = None

class ActorRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)


def superdocs(settings: Settings) -> SuperDocsService:
    if settings.superdocs_mcp_api_key is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SuperDocs MCP is not configured")
    return SuperDocsService(SuperDocsConnection(mcp_url=settings.superdocs_mcp_url, mcp_api_key=settings.superdocs_mcp_api_key, timeout_seconds=settings.superdocs_mcp_timeout_seconds))

@router.post("/series", response_model=SeriesView, status_code=201)
async def create_series(payload: SeriesCreate, session: Session) -> Series:
    record = Series(name=payload.name, description=payload.description)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record

@router.get("/series", response_model=list[SeriesView])
async def list_series(session: Session) -> list[Series]:
    return list((await session.scalars(select(Series).order_by(Series.updated_at.desc()))).all())

@router.get("/series/{series_id}")
async def get_series(series_id: UUID, session: Session) -> dict[str, Any]:
    record = await session.get(Series, series_id)
    if not record:
        raise HTTPException(404, "Series not found")
    counts = {}
    for name, model in (("chapters", Document), ("facts", BibleFact), ("findings", ContinuityFinding)):
        counts[name] = await session.scalar(select(func.count()).select_from(model).where(model.series_id == series_id))
    return {"id": record.id, "name": record.name, "description": record.description, "created_at": record.created_at, "counts": counts}

@router.post("/series/{series_id}/documents", status_code=201)
async def upload_document(series_id: UUID, session: Session, settings: Config, file: UploadFile = File(...), actor: str = Form("user")) -> dict[str, Any]:
    if not await session.get(Series, series_id):
        raise HTTPException(404, "Series not found")
    content = await file.read(settings.max_upload_bytes + 1)
    try:
        record = await IngestionService(session, superdocs(settings), settings.max_upload_bytes).ingest(series_id, file.filename or "", content, actor)
        await session.commit()
        return {"id": record.id, "filename": record.filename, "status": record.status, "session_id": record.superdocs_session_id}
    except (ValueError, SuperDocsServiceError) as error:
        await session.rollback()
        raise HTTPException(422, str(error)) from error

@router.post("/series/{series_id}/runs", status_code=201)
async def create_run(series_id: UUID, payload: RunCreate, session: Session) -> dict[str, Any]:
    if not await session.get(Series, series_id):
        raise HTTPException(404, "Series not found")
    run = WorkflowRun(series_id=series_id, state={"document_ids": [str(value) for value in payload.document_ids]}, status="READY")
    session.add(run)
    await session.commit()
    return {"id": run.id, "series_id": run.series_id, "status": run.status, "current_stage": run.current_stage}

@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, session: Session) -> dict[str, Any]:
    run = await session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {"id": run.id, "series_id": run.series_id, "status": run.status, "current_stage": run.current_stage, "completed_stages": run.completed_stages, "state": run.state, "errors": run.errors, "updated_at": run.updated_at}

@router.get("/series/{series_id}/bible")
async def get_bible(series_id: UUID, session: Session) -> list[dict[str, Any]]:
    facts = (await session.scalars(select(BibleFact).where(BibleFact.series_id == series_id).order_by(BibleFact.kind, BibleFact.entity, BibleFact.attribute, BibleFact.version.desc()))).all()
    return [{"id": fact.id, "kind": fact.kind, "entity": fact.entity, "attribute": fact.attribute, "value": fact.value, "version": fact.version, "is_current": fact.is_current, "confidence": fact.confidence} for fact in facts]

@router.get("/series/{series_id}/findings")
async def get_findings(series_id: UUID, session: Session) -> list[dict[str, Any]]:
    findings = (await session.scalars(select(ContinuityFinding).where(ContinuityFinding.series_id == series_id).order_by(ContinuityFinding.created_at.desc()))).all()
    return [{"id": item.id, "type": item.type, "entity": item.entity, "attribute": item.attribute, "existing_value": item.existing_value, "new_value": item.new_value, "explanation": item.explanation, "confidence": item.confidence, "severity": item.severity, "status": item.status} for item in findings]

async def resolve(finding_id: UUID, resolution: Resolution, payload: ActorRequest | ReviewRequest, session: AsyncSession) -> dict[str, str]:
    finding = await session.get(ContinuityFinding, finding_id, with_for_update=True)
    if not finding or finding.status != "OPEN":
        raise HTTPException(409, "Finding is missing or already resolved")
    finding.status = resolution.value
    rationale = payload.rationale if isinstance(payload, ReviewRequest) else ""
    session.add(ReviewDecision(finding_id=finding.id, actor=payload.actor, resolution=resolution.value, rationale=rationale))
    session.add(AuditEvent(run_id=finding.run_id, actor=payload.actor, entity="finding", entity_id=str(finding.id), operation="FINDING_APPROVED" if resolution != Resolution.REJECT else "FINDING_REJECTED", metadata_json={"resolution": resolution.value}))
    await session.commit()
    return {"status": finding.status}

@router.post("/findings/{finding_id}/approve")
async def approve_finding(finding_id: UUID, payload: ReviewRequest, session: Session):
    if payload.resolution not in (Resolution.KEEP_EXISTING, Resolution.ACCEPT_NEW):
        raise HTTPException(422, "approve requires KEEP_EXISTING or ACCEPT_NEW")
    return await resolve(finding_id, payload.resolution, payload, session)

@router.post("/findings/{finding_id}/reject")
async def reject_finding(finding_id: UUID, payload: ActorRequest, session: Session):
    return await resolve(finding_id, Resolution.REJECT, payload, session)

@router.post("/findings/{finding_id}/intentional-change")
async def intentional_change(finding_id: UUID, payload: ActorRequest, session: Session):
    return await resolve(finding_id, Resolution.INTENTIONAL_CHANGE, payload, session)

@router.post("/findings/{finding_id}/propose-edit", status_code=201)
async def propose_edit(finding_id: UUID, payload: ProposedEditRequest, session: Session, settings: Config) -> dict[str, Any]:
    finding = await session.get(ContinuityFinding, finding_id)
    if not finding or finding.status != Resolution.KEEP_EXISTING.value:
        raise HTTPException(409, "KEEP_EXISTING must be recorded before proposing an edit")
    document = await session.scalar(select(Document).where(Document.series_id == finding.series_id).order_by(Document.created_at.desc()))
    if not document:
        raise HTTPException(404, "Target document not found")
    result = await superdocs(settings).send_edit_instruction(EditInstructionRequest(session_id=document.superdocs_session_id, document_id=document.superdocs_document_id, message=payload.instruction, response_mode="compact"))
    job_id = result.get("job_id")
    if not job_id:
        raise HTTPException(502, "SuperDocs did not return an edit job ID")
    change = ProposedChange(finding_id=finding.id, document_id=document.id, instruction=payload.instruction, superdocs_job_id=str(job_id), superdocs_change_id=result.get("change_id"), original_html=result.get("original_html"), proposed_html=result.get("proposed_html"), status="AWAITING_APPROVAL")
    session.add(change)
    await session.flush()
    session.add(AuditEvent(run_id=finding.run_id, actor=payload.actor, entity="proposed_change", entity_id=str(change.id), operation="EDIT_PROPOSED", metadata_json={"job_id": str(job_id)}))
    await session.commit()
    return {"id": change.id, "status": change.status, "job_id": change.superdocs_job_id, "change_id": change.superdocs_change_id, "original": change.original_html, "proposed": change.proposed_html}

@router.post("/proposed-changes/{change_id}/approve")
async def approve_proposed_change(change_id: UUID, payload: ApprovalRequest, session: Session, settings: Config) -> dict[str, Any]:
    change = await session.get(ProposedChange, change_id, with_for_update=True)
    if not change or change.status != "AWAITING_APPROVAL":
        raise HTTPException(409, "Change is missing or already decided")
    document = await session.get(Document, change.document_id)
    result = await superdocs(settings).approve_change(ApproveChangeRequest(session_id=document.superdocs_session_id, job_id=change.superdocs_job_id, change_id=change.superdocs_change_id, approved=payload.approved, feedback=payload.feedback))
    change.status = "APPROVED" if payload.approved else "REJECTED"
    session.add(AuditEvent(actor=payload.actor, entity="proposed_change", entity_id=str(change.id), operation="EDIT_APPROVED" if payload.approved else "EDIT_REJECTED", metadata_json={}))
    await session.commit()
    return {"status": change.status, "superdocs": result}

@router.post("/export")
async def export_document(payload: ExportRequest, session: Session, settings: Config) -> dict[str, Any]:
    document = await session.get(Document, payload.document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    result = await superdocs(settings).export_document(ExportDocumentRequest(session_id=document.superdocs_session_id, format=payload.format, options=ExportOptions(filename=payload.filename)))
    session.add(AuditEvent(actor="user", entity="document", entity_id=str(document.id), operation="DOCUMENT_EXPORTED", metadata_json={"format": payload.format}))
    await session.commit()
    return result
