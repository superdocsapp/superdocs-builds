from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.document import Document, ProcessingStatus
from app.domain.packet import Packet
from app.workers.processor import process_document

router = APIRouter()


@router.post("/{packet_id}/start")
async def start_processing(
    packet_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(Document).where(
            Document.packet_id == packet_id,
            Document.processing_status.in_([ProcessingStatus.QUEUED, ProcessingStatus.FAILED]),
        )
    )
    documents = result.scalars().all()

    for doc in documents:
        background_tasks.add_task(process_document, str(doc.id))

    return {
        "message": f"Processing started for {len(documents)} documents",
        "documents_queued": [{"id": str(d.id), "filename": d.original_filename} for d in documents],
    }


@router.get("/{packet_id}/status")
async def get_processing_status(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(select(Document).where(Document.packet_id == packet_id))
    documents = result.scalars().all()

    status_counts = {}
    for doc in documents:
        status_counts[doc.processing_status.value] = (
            status_counts.get(doc.processing_status.value, 0) + 1
        )

    return {
        "packet_id": packet_id,
        "total_documents": len(documents),
        "status_breakdown": status_counts,
        "documents": [
            {
                "id": str(doc.id),
                "filename": doc.original_filename,
                "status": doc.processing_status.value,
                "page_count": doc.page_count,
                "is_searchable": doc.is_searchable,
                "error": doc.processing_error,
                "retry_count": doc.retry_count,
            }
            for doc in documents
        ],
    }


@router.get("/{packet_id}/{document_id}/status")
async def get_document_status(
    packet_id: UUID, document_id: UUID, session: AsyncSession = Depends(get_session)
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "id": str(document.id),
        "filename": document.original_filename,
        "status": document.processing_status.value,
        "page_count": document.page_count,
        "is_searchable": document.is_searchable,
        "error": document.processing_error,
        "retry_count": document.retry_count,
        "last_completed_step": document.last_completed_step,
    }


@router.post("/{packet_id}/{document_id}/retry")
async def retry_document(
    packet_id: UUID,
    document_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.processing_status not in [ProcessingStatus.FAILED, ProcessingStatus.QUEUED]:
        raise HTTPException(status_code=400, detail="Document is not in a retryable state")

    document.processing_status = ProcessingStatus.QUEUED
    document.processing_error = None
    session.add(
        AuditEvent(
            packet_id=packet_id,
            document_id=document.id,
            event_type=AuditEventType.PROCESSING_RETRIED,
            user_id="system",
            event_metadata={
                "filename": document.original_filename,
                "retry_count": document.retry_count,
            },
        )
    )
    await session.commit()

    background_tasks.add_task(process_document, str(document.id))

    return {"message": "Document queued for retry", "document_id": str(document.id)}
