from __future__ import annotations
from typing import Annotated, Any
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from series_bible.application.ingestion import IngestionService
from series_bible.application.chat import ChatService
from series_bible.application.bible import BibleService
from series_bible.application.run_service import WorkflowRunner
from series_bible.config import Settings, get_settings
from series_bible.domain.schemas import ApprovalRequest, ExtractedFact, ProposedEditRequest, Resolution, ReviewRequest, SeriesCreate, SeriesView
from series_bible.infrastructure.auth import AuthenticationError, issue_token, verify_google_credential, verify_token
from series_bible.infrastructure.database import AuditEvent, BibleFact, ChatMessage, ChatSession, ContinuityFinding, Document, Evidence, ProposedChange, ReviewDecision, Series, StoryEvent, User, WorkflowRun, get_session
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

class GoogleCredential(BaseModel):
    credential: str = Field(min_length=20, max_length=10000)

class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)


async def current_user(
    session: Session,
    settings: Config,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in is required")
    try:
        claims = verify_token(authorization.removeprefix("Bearer "), settings)
        user_id = UUID(str(claims["sub"]))
    except (AuthenticationError, KeyError, ValueError) as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Please sign in again.") from error
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User account not found")
    return user


def superdocs(settings: Settings) -> SuperDocsService:
    if settings.superdocs_mcp_api_key is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SuperDocs MCP is not configured")
    return SuperDocsService(SuperDocsConnection(mcp_url=settings.superdocs_mcp_url, mcp_api_key=settings.superdocs_mcp_api_key, timeout_seconds=settings.superdocs_mcp_timeout_seconds))

@router.post("/auth/google")
async def google_sign_in(payload: GoogleCredential, session: Session, settings: Config) -> dict[str, Any]:
    try:
        claims = verify_google_credential(payload.credential, settings)
    except AuthenticationError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    user = await session.scalar(select(User).where(User.google_subject == str(claims["sub"])))
    if user is None:
        user = User(
            google_subject=str(claims["sub"]),
            email=str(claims["email"]).casefold(),
            display_name=str(claims.get("name") or claims["email"]),
            avatar_url=claims.get("picture"),
        )
        session.add(user)
    else:
        user.email = str(claims["email"]).casefold()
        user.display_name = str(claims.get("name") or user.email)
        user.avatar_url = claims.get("picture")
    await session.commit()
    await session.refresh(user)
    return {"token": issue_token(user.id, settings), "user": {"id": str(user.id), "email": user.email, "name": user.display_name, "avatar_url": user.avatar_url}}

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

@router.delete("/series/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series(series_id: UUID, session: Session) -> None:
    """Permanently remove a series and its cascade-owned workspace data."""
    record = await session.get(Series, series_id)
    if record is None:
        raise HTTPException(404, "Series not found")
    # These dependent records intentionally preserve a durable audit trail in
    # normal operation, so their database foreign keys do not cascade. Delete
    # them in dependency order for an explicit permanent series deletion.
    run_ids = select(WorkflowRun.id).where(WorkflowRun.series_id == series_id)
    finding_ids = select(ContinuityFinding.id).where(ContinuityFinding.series_id == series_id)
    await session.execute(delete(ReviewDecision).where(ReviewDecision.finding_id.in_(finding_ids)))
    await session.execute(delete(ProposedChange).where(ProposedChange.finding_id.in_(finding_ids)))
    # Evidence points at documents and is intentionally not configured with a
    # database cascade; remove it before the series delete cascades documents.
    await session.execute(delete(Evidence).where(Evidence.document_id.in_(select(Document.id).where(Document.series_id == series_id))))
    await session.execute(delete(StoryEvent).where(StoryEvent.series_id == series_id))
    await session.execute(delete(AuditEvent).where(AuditEvent.run_id.in_(run_ids)))
    await session.delete(record)
    await session.commit()

@router.post("/series/{series_id}/documents", status_code=201)
async def upload_document(series_id: UUID, session: Session, settings: Config, file: UploadFile = File(...), actor: str = Form("user")) -> dict[str, Any]:
    if not await session.get(Series, series_id):
        raise HTTPException(404, "Series not found")
    content = await file.read(settings.max_upload_bytes + 1)
    # Build the runner first so a bad LLM/extraction configuration fails fast with a clear
    # 422 before any document is imported, instead of leaving an imported document with no
    # analysis behind it.
    try:
        runner = WorkflowRunner(session, settings)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    try:
        record = await IngestionService(session, superdocs(settings), settings.max_upload_bytes).ingest(series_id, file.filename or "", content, actor)
        await session.commit()
        # Uploading a chapter must also execute the analysis pipeline. Previously
        # this endpoint only persisted chunks, so the chapter count increased
        # while the Bible and findings remained empty.
        run = WorkflowRun(series_id=series_id, state={"document_ids": [str(record.id)]}, status="READY")
        session.add(run)
        await session.commit()
        run = await runner.execute(run.id)
        return {
            "id": record.id,
            "filename": record.filename,
            "status": record.status,
            "session_id": record.superdocs_session_id,
            "run_id": run.id,
            "run_status": run.status,
            "run_errors": run.errors,
        }
    except ValueError as error:
        await session.rollback()
        raise HTTPException(422, str(error)) from error
    except SuperDocsServiceError as error:
        await session.rollback()
        raise HTTPException(502, str(error)) from error

@router.post("/series/{series_id}/runs", status_code=201)
async def create_run(series_id: UUID, payload: RunCreate, session: Session, settings: Config) -> dict[str, Any]:
    if not await session.get(Series, series_id):
        raise HTTPException(404, "Series not found")
    try:
        runner = WorkflowRunner(session, settings)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    run = WorkflowRun(series_id=series_id, state={"document_ids": [str(value) for value in payload.document_ids]}, status="READY")
    session.add(run)
    await session.commit()
    run = await runner.execute(run.id)
    return {"id": run.id, "series_id": run.series_id, "status": run.status, "current_stage": run.current_stage, "completed_stages": run.completed_stages, "errors": run.errors}

@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, session: Session) -> dict[str, Any]:
    run = await session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {"id": run.id, "series_id": run.series_id, "status": run.status, "current_stage": run.current_stage, "completed_stages": run.completed_stages, "state": run.state, "errors": run.errors, "updated_at": run.updated_at}

@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: UUID, session: Session, settings: Config) -> dict[str, Any]:
    run = await session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status not in ("FAILED", "RUNNING"):
        raise HTTPException(409, "Only a failed or stuck run can be retried")
    try:
        runner = WorkflowRunner(session, settings)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    run = await runner.execute(run.id)
    return {"id": run.id, "series_id": run.series_id, "status": run.status, "current_stage": run.current_stage, "completed_stages": run.completed_stages, "errors": run.errors}

@router.get("/series/{series_id}/bible")
async def get_bible(series_id: UUID, session: Session) -> list[dict[str, Any]]:
    facts = (await session.scalars(select(BibleFact).where(BibleFact.series_id == series_id).order_by(BibleFact.kind, BibleFact.entity, BibleFact.attribute, BibleFact.version.desc()))).all()
    return [{"id": fact.id, "kind": fact.kind, "entity": fact.entity, "attribute": fact.attribute, "value": fact.value, "version": fact.version, "is_current": fact.is_current, "confidence": fact.confidence} for fact in facts]

@router.get("/series/{series_id}/findings")
async def get_findings(series_id: UUID, session: Session) -> list[dict[str, Any]]:
    findings = (await session.scalars(select(ContinuityFinding).where(ContinuityFinding.series_id == series_id).order_by(ContinuityFinding.created_at.desc()))).all()
    result = []
    for item in findings:
        new_source = await session.scalar(select(Evidence).where(Evidence.finding_id == item.id, Evidence.role == "NEW"))
        old_source = await session.scalar(select(Evidence).where(Evidence.fact_id == item.existing_fact_id)) if item.existing_fact_id else await session.scalar(select(Evidence).where(Evidence.finding_id == item.id, Evidence.role == "OLD"))
        citation = lambda source: None if source is None else {"chapter": source.chapter, "section": source.section, "page": source.page, "chunk_id": source.chunk_id, "evidence_text": source.exact_text}
        result.append({"id": item.id, "type": item.type, "entity": item.entity, "attribute": item.attribute, "existing_value": item.existing_value, "new_value": item.new_value, "existing_evidence": citation(old_source), "new_evidence": citation(new_source), "explanation": item.explanation, "confidence": item.confidence, "severity": item.severity, "status": item.status})
    return result

@router.get("/series/{series_id}/chat")
async def chat_history(series_id: UUID, user: Annotated[User, Depends(current_user)], session: Session) -> dict[str, Any]:
    chat_session = await session.scalar(
        select(ChatSession).where(ChatSession.series_id == series_id, ChatSession.user_id == user.id).order_by(ChatSession.updated_at.desc())
    )
    if chat_session is None:
        return {"session_id": None, "messages": []}
    messages = (await session.scalars(select(ChatMessage).where(ChatMessage.session_id == chat_session.id).order_by(ChatMessage.created_at))).all()
    return {"session_id": chat_session.id, "messages": [{"id": message.id, "role": message.role, "content": message.content, "citations": message.citations, "grounded": message.grounded, "created_at": message.created_at} for message in messages]}

@router.post("/series/{series_id}/chat")
async def ask_chat(series_id: UUID, payload: ChatRequest, user: Annotated[User, Depends(current_user)], session: Session, settings: Config) -> dict[str, Any]:
    if not await session.get(Series, series_id):
        raise HTTPException(404, "Series not found")
    answer = await ChatService(session, settings).ask(series_id, payload.question, user.id)
    await session.commit()
    return answer

@router.delete("/series/{series_id}/chat", status_code=status.HTTP_204_NO_CONTENT)
async def clear_chat(series_id: UUID, user: Annotated[User, Depends(current_user)], session: Session) -> None:
    """Clear only the current user's persistent chat history for this series."""
    chat_session = await session.scalar(
        select(ChatSession).where(ChatSession.series_id == series_id, ChatSession.user_id == user.id)
    )
    if chat_session is not None:
        await session.execute(delete(ChatMessage).where(ChatMessage.session_id == chat_session.id))
        await session.delete(chat_session)
        await session.commit()

async def resolve(finding_id: UUID, resolution: Resolution, payload: ActorRequest | ReviewRequest, session: AsyncSession) -> dict[str, str]:
    finding = await session.get(ContinuityFinding, finding_id, with_for_update=True)
    if not finding or finding.status != "OPEN":
        raise HTTPException(409, "Finding is missing or already resolved")
    finding.status = resolution.value
    rationale = payload.rationale if isinstance(payload, ReviewRequest) else ""
    if resolution is Resolution.ACCEPT_NEW:
        new_fact = ExtractedFact.model_validate(finding.new_fact, strict=False)
        existing = await session.get(BibleFact, finding.existing_fact_id) if finding.existing_fact_id else None
        fact = await BibleService(session).add_version(finding.series_id, new_fact, existing)
        session.add(AuditEvent(run_id=finding.run_id, actor=payload.actor, entity="bible_fact", entity_id=str(fact.id), operation="BIBLE_UPDATED", metadata_json={"supersedes_id": str(existing.id) if existing else None}))
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
    service = superdocs(settings)
    result = await service.send_edit_instruction(EditInstructionRequest(session_id=document.superdocs_session_id, document_id=document.superdocs_document_id, message=payload.instruction, response_mode="compact"))
    job_id = result.get("job_id")
    if not job_id:
        raise HTTPException(502, "SuperDocs did not return an edit job ID")
    try:
        proposal = await service.wait_for_edit_proposal(
            str(job_id),
            timeout_seconds=settings.superdocs_job_timeout_seconds,
            poll_seconds=settings.superdocs_job_poll_seconds,
        )
    except SuperDocsServiceError as error:
        raise HTTPException(502, str(error)) from error
    change = ProposedChange(finding_id=finding.id, document_id=document.id, instruction=payload.instruction, superdocs_job_id=proposal.job_id, superdocs_change_id=proposal.change_id, original_html=proposal.original_html, proposed_html=proposal.proposed_html, status="READY_FOR_APPROVAL")
    session.add(change)
    await session.flush()
    session.add(AuditEvent(run_id=finding.run_id, actor=payload.actor, entity="proposed_change", entity_id=str(change.id), operation="EDIT_PROPOSED", metadata_json={"job_id": str(job_id)}))
    await session.commit()
    return {"id": change.id, "status": change.status, "job_id": change.superdocs_job_id, "change_id": change.superdocs_change_id, "original": change.original_html, "proposed": change.proposed_html}

@router.post("/proposed-changes/{change_id}/approve")
async def approve_proposed_change(change_id: UUID, payload: ApprovalRequest, session: Session, settings: Config) -> dict[str, Any]:
    change = await session.get(ProposedChange, change_id, with_for_update=True)
    if not change or change.status != "READY_FOR_APPROVAL":
        raise HTTPException(409, "Change is missing or already decided")
    document = await session.get(Document, change.document_id)
    finding = await session.get(ContinuityFinding, change.finding_id)
    result = await superdocs(settings).approve_change(ApproveChangeRequest(session_id=document.superdocs_session_id, job_id=change.superdocs_job_id, change_id=change.superdocs_change_id, approved=payload.approved, feedback=payload.feedback))
    change.status = "APPROVED" if payload.approved else "REJECTED"
    session.add(AuditEvent(run_id=finding.run_id if finding else None, actor=payload.actor, entity="proposed_change", entity_id=str(change.id), operation="EDIT_APPROVED" if payload.approved else "EDIT_REJECTED", metadata_json={"job_id": change.superdocs_job_id, "change_id": change.superdocs_change_id}))
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
