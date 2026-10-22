from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.database import get_session
from app.domain.packet import Packet
from app.domain.document import Document
from app.domain.audit import AuditEvent

router = APIRouter()


def serialize_event(event: AuditEvent, document_name: str | None) -> dict:
    return {
        "id": str(event.id),
        "packet_id": str(event.packet_id) if event.packet_id else None,
        "document_id": str(event.document_id) if event.document_id else None,
        "document_name": document_name,
        "event_type": event.event_type.value,
        "user_id": event.user_id,
        "metadata": event.event_metadata,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
    }


@router.get("/{packet_id}")
async def get_audit_trail(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    doc_ids_result = await session.execute(
        select(Document.id).where(Document.packet_id == packet_id)
    )
    doc_ids = [row[0] for row in doc_ids_result.fetchall()]

    events_result = await session.execute(
        select(AuditEvent)
        .where(
            or_(
                AuditEvent.packet_id == packet_id,
                AuditEvent.document_id.in_(doc_ids) if doc_ids else False,
            )
        )
        .order_by(AuditEvent.timestamp.desc())
    )
    events = events_result.scalars().all()

    document_names = {}
    if doc_ids:
        docs_result = await session.execute(
            select(Document).where(Document.id.in_(doc_ids))
        )
        for doc in docs_result.scalars().all():
            document_names[str(doc.id)] = doc.original_filename

    return {
        "packet_id": packet_id,
        "total_events": len(events),
        "events": [
            serialize_event(event, document_names.get(str(event.document_id)) if event.document_id else None)
            for event in events
        ],
    }


@router.get("/{packet_id}/{document_id}")
async def get_document_audit(packet_id: UUID, document_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    events_result = await session.execute(
        select(AuditEvent)
        .where(
            or_(
                AuditEvent.document_id == document_id,
                AuditEvent.packet_id == packet_id,
            )
        )
        .order_by(AuditEvent.timestamp.desc())
    )
    events = events_result.scalars().all()

    return {
        "packet_id": packet_id,
        "document_id": document_id,
        "document_name": document.original_filename,
        "total_events": len(events),
        "events": [
            serialize_event(event, document.original_filename)
            for event in events
        ],
    }