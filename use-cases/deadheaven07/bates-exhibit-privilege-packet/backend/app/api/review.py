from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.document import Document, ProcessingStatus
from app.domain.packet import Packet
from app.services.superdocs_adapter import SuperDocsAPIError
from app.services.superdocs_integration import SuperDocsIntegrationService, get_superdocs_service

router = APIRouter()


def _translate_superdocs_error(exc: Exception) -> HTTPException:
    """Map upstream provider errors to controlled API responses without
    leaking API keys, raw provider bodies, or internal stack traces."""
    if isinstance(exc, SuperDocsAPIError):
        if 400 <= exc.status_code < 500:
            return HTTPException(
                status_code=exc.status_code, detail="SuperDocs API rejected the request"
            )
        return HTTPException(status_code=502, detail="SuperDocs API error")
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return HTTPException(status_code=504, detail="SuperDocs service unavailable")
    return HTTPException(status_code=500, detail="AI service error")


class AIAnalysisRequest(BaseModel):
    instruction: str
    approval_mode: str = "ask_every_time"
    model_tier: str = "core"


class ApproveChangesRequest(BaseModel):
    job_id: str
    approved: bool
    changes: list[dict]
    feedback: str | None = None


class ContinueJobRequest(BaseModel):
    job_id: str
    continue_job: bool


@router.post("/{packet_id}/documents/{document_id}/analyze")
async def request_ai_analysis(
    packet_id: UUID,
    document_id: UUID,
    request: AIAnalysisRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsIntegrationService = Depends(get_superdocs_service),
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.processing_status != ProcessingStatus.COMPLETED:
        raise HTTPException(
            status_code=400, detail="Document must be fully processed before AI analysis"
        )

    try:
        job_id = await superdocs.request_ai_analysis(
            session=session,
            document=document,
            instruction=request.instruction,
            approval_mode=request.approval_mode,
            model_tier=request.model_tier,
        )
    except Exception as e:
        document.processing_status = ProcessingStatus.COMPLETED
        session.add(
            AuditEvent(
                packet_id=packet_id,
                document_id=document.id,
                event_type=AuditEventType.AI_ANALYSIS_FAILED,
                user_id="system",
                event_metadata={"error": type(e).__name__},
            )
        )
        await session.commit()
        raise _translate_superdocs_error(e) from e

    session.add(
        AuditEvent(
            packet_id=packet_id,
            document_id=document.id,
            event_type=AuditEventType.AI_ANALYSIS_STARTED,
            user_id="system",
            event_metadata={"job_id": job_id, "instruction": request.instruction},
        )
    )
    await session.commit()

    return {
        "message": "AI analysis started",
        "job_id": job_id,
        "document_id": str(document.id),
    }


@router.get("/{packet_id}/documents/{document_id}/analysis-status")
async def get_analysis_status(
    packet_id: UUID,
    document_id: UUID,
    job_id: str,
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsIntegrationService = Depends(get_superdocs_service),
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    job_status = await superdocs.poll_ai_job(job_id)

    if job_status.status == "awaiting_approval":
        await _mark_waiting_review(session, document, job_id)
        proposed_changes = await superdocs.get_proposed_changes(job_id)
        return {
            "status": job_status.status,
            "job_id": job_id,
            "awaiting_kind": proposed_changes.awaiting_kind,
            "continue_prompt": proposed_changes.continue_prompt,
            "changes": [
                {
                    "change_id": c.change_id,
                    "operation": c.operation,
                    "chunk_id": c.chunk_id,
                    "old_html": c.old_html,
                    "new_html": c.new_html,
                    "ai_explanation": c.ai_explanation,
                    "insert_after_chunk_id": c.insert_after_chunk_id,
                    "document_id": c.document_id,
                }
                for c in proposed_changes.changes
            ],
        }

    if job_status.status == "completed":
        await _mark_completed(session, document, job_id)

    if job_status.status == "failed":
        await _mark_ai_failed(session, document, job_id, job_status.error)

    return {
        "status": job_status.status,
        "job_id": job_id,
        "result": job_status.result,
        "error": job_status.error,
    }


@router.post("/{packet_id}/documents/{document_id}/approve-changes")
async def approve_ai_changes(
    packet_id: UUID,
    document_id: UUID,
    request: ApproveChangesRequest,
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsIntegrationService = Depends(get_superdocs_service),
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        job_status = await superdocs.approve_changes(
            document=document,
            job_id=request.job_id,
            approved=request.approved,
            changes=request.changes,
            feedback=request.feedback,
        )
    except Exception as e:
        raise _translate_superdocs_error(e) from e

    session.add(
        AuditEvent(
            packet_id=packet_id,
            document_id=document.id,
            event_type=AuditEventType.CHANGE_APPROVED
            if request.approved
            else AuditEventType.CHANGE_REJECTED,
            user_id="system",
            event_metadata={"job_id": request.job_id, "change_count": len(request.changes)},
        )
    )
    if job_status.status == "completed":
        document.processing_status = ProcessingStatus.COMPLETED
        session.add(
            AuditEvent(
                packet_id=packet_id,
                document_id=document.id,
                event_type=AuditEventType.AI_ANALYSIS_COMPLETED,
                user_id="system",
                event_metadata={"job_id": request.job_id},
            )
        )
    elif job_status.status == "awaiting_approval":
        document.processing_status = ProcessingStatus.WAITING_REVIEW
    await session.commit()

    return {
        "status": job_status.status,
        "job_id": job_status.job_id,
        "result": job_status.result,
    }


@router.post("/{packet_id}/documents/{document_id}/continue-job")
async def continue_ai_job(
    packet_id: UUID,
    document_id: UUID,
    request: ContinueJobRequest,
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsIntegrationService = Depends(get_superdocs_service),
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        job_status = await superdocs.continue_job(
            document=document,
            job_id=request.job_id,
            continue_job=request.continue_job,
        )
    except Exception as e:
        raise _translate_superdocs_error(e) from e

    session.add(
        AuditEvent(
            packet_id=packet_id,
            document_id=document.id,
            event_type=AuditEventType.CHANGE_PROPOSED
            if request.continue_job
            else AuditEventType.CHANGE_REJECTED,
            user_id="system",
            event_metadata={"job_id": request.job_id},
        )
    )
    if job_status.status == "completed":
        document.processing_status = ProcessingStatus.COMPLETED
        session.add(
            AuditEvent(
                packet_id=packet_id,
                document_id=document.id,
                event_type=AuditEventType.AI_ANALYSIS_COMPLETED,
                user_id="system",
                event_metadata={"job_id": request.job_id},
            )
        )
    elif job_status.status == "awaiting_approval":
        document.processing_status = ProcessingStatus.WAITING_REVIEW
    await session.commit()

    return {
        "status": job_status.status,
        "job_id": job_status.job_id,
        "result": job_status.result,
    }


@router.post("/{packet_id}/documents/{document_id}/export")
async def export_superdocs_document(
    packet_id: UUID,
    document_id: UUID,
    format: str = "pdf",
    options: dict | None = None,
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsIntegrationService = Depends(get_superdocs_service),
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        export_result = await superdocs.export_document(
            document=document,
            format=format,
            options=options,
        )
    except Exception as e:
        raise _translate_superdocs_error(e) from e

    session.add(
        AuditEvent(
            packet_id=packet_id,
            document_id=document.id,
            event_type=AuditEventType.EXPORT_STARTED,
            user_id="system",
            event_metadata={"format": format, "filename": export_result.filename},
        )
    )
    await session.commit()

    return {
        "download_url": export_result.download_url,
        "filename": export_result.filename,
        "format": export_result.format,
    }


@router.get("/{packet_id}/documents/{document_id}/history")
async def get_document_history(
    packet_id: UUID,
    document_id: UUID,
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsIntegrationService = Depends(get_superdocs_service),
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        history = await superdocs.get_session_history(document)
    except Exception as e:
        raise _translate_superdocs_error(e) from e

    return history


@router.get("/{packet_id}/ai-changes")
async def get_packet_ai_changes(
    packet_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(Document).where(
            Document.packet_id == packet_id,
            Document.processing_status.in_(
                [ProcessingStatus.AI_ANALYSIS, ProcessingStatus.WAITING_REVIEW]
            ),
        )
    )
    documents = result.scalars().all()

    return {
        "documents_awaiting_review": [
            {
                "document_id": str(doc.id),
                "filename": doc.original_filename,
                "status": doc.processing_status.value,
                "superdocs_session_id": doc.superdocs_session_id,
            }
            for doc in documents
        ]
    }


async def _mark_waiting_review(session: AsyncSession, document: Document, job_id: str) -> None:
    document.processing_status = ProcessingStatus.WAITING_REVIEW
    session.add(
        AuditEvent(
            packet_id=document.packet_id,
            document_id=document.id,
            event_type=AuditEventType.CHANGE_PROPOSED,
            user_id="system",
            event_metadata={"job_id": job_id},
        )
    )
    await session.commit()


async def _mark_completed(session: AsyncSession, document: Document, job_id: str) -> None:
    document.processing_status = ProcessingStatus.COMPLETED
    session.add(
        AuditEvent(
            packet_id=document.packet_id,
            document_id=document.id,
            event_type=AuditEventType.AI_ANALYSIS_COMPLETED,
            user_id="system",
            event_metadata={"job_id": job_id},
        )
    )
    await session.commit()


async def _mark_ai_failed(
    session: AsyncSession, document: Document, job_id: str, error: str | None
) -> None:
    document.processing_status = ProcessingStatus.COMPLETED
    session.add(
        AuditEvent(
            packet_id=document.packet_id,
            document_id=document.id,
            event_type=AuditEventType.AI_ANALYSIS_FAILED,
            user_id="system",
            event_metadata={"job_id": job_id, "error": error},
        )
    )
    await session.commit()
