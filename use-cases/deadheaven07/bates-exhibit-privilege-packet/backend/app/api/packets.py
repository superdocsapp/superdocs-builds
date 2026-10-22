import shutil
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import UUID

from app.database import get_session
from app.config import get_settings
from app.domain.packet import Packet
from app.domain.document import Document, ProcessingStatus
from app.domain.audit import AuditEvent, AuditEventType
from app.services.storage import cleanup_document_files

router = APIRouter()


class PacketCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    bates_prefix: str = "CASE-"
    bates_start_number: int = Field(1, ge=0)
    bates_padding: int = Field(6, ge=1)


class PacketUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    bates_prefix: str | None = None
    bates_start_number: int | None = Field(None, ge=0)
    bates_padding: int | None = Field(None, ge=1)


def serialize_packet(packet: Packet, document_count: int, total_pages: int, completed_count: int, failed_count: int) -> dict:
    return {
        "id": str(packet.id),
        "name": packet.name,
        "description": packet.description,
        "bates_prefix": packet.bates_prefix,
        "bates_start_number": packet.bates_start_number,
        "bates_padding": packet.bates_padding,
        "document_count": document_count,
        "total_pages": total_pages,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "status": "completed" if completed_count == document_count and document_count > 0
        else "failed" if failed_count > 0
        else "in_progress" if document_count > 0
        else "draft",
        "created_at": packet.created_at.isoformat() if packet.created_at else None,
        "updated_at": packet.updated_at.isoformat() if packet.updated_at else None,
    }


async def _packet_summary(session: AsyncSession, packet_id) -> tuple[int, int, int, int]:
    result = await session.execute(
        select(
            func.count(Document.id),
            func.coalesce(func.sum(Document.page_count), 0),
            func.count(Document.id).filter(Document.processing_status == ProcessingStatus.COMPLETED),
            func.count(Document.id).filter(Document.processing_status == ProcessingStatus.FAILED),
        ).where(Document.packet_id == packet_id)
    )
    row = result.one()
    return int(row[0]), int(row[1]), int(row[2]), int(row[3])


@router.post("")
async def create_packet(
    request: PacketCreateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
):
    packet = Packet(
        name=request.name,
        description=request.description,
        bates_prefix=request.bates_prefix,
        bates_start_number=request.bates_start_number,
        bates_padding=request.bates_padding,
    )
    session.add(packet)
    await session.flush()
    session.add(AuditEvent(
        packet_id=packet.id,
        event_type=AuditEventType.PACKET_CREATED,
        user_id="system",
        event_metadata={"name": packet.name},
    ))
    await session.commit()
    await session.refresh(packet)
    return serialize_packet(packet, 0, 0, 0, 0)


@router.get("")
async def list_packets(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Packet).order_by(Packet.updated_at.desc())
    )
    packets = result.scalars().all()

    packets_data = []
    for packet in packets:
        document_count, total_pages, completed_count, failed_count = await _packet_summary(session, packet.id)
        packets_data.append(serialize_packet(packet, document_count, total_pages, completed_count, failed_count))

    return packets_data


@router.get("/{packet_id}")
async def get_packet(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    document_count, total_pages, completed_count, failed_count = await _packet_summary(session, packet.id)
    return serialize_packet(packet, document_count, total_pages, completed_count, failed_count)


@router.patch("/{packet_id}")
async def update_packet(
    packet_id: UUID,
    request: PacketUpdateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(packet, field, value)

    session.add(AuditEvent(
        packet_id=packet.id,
        event_type=AuditEventType.PACKET_UPDATED,
        user_id="system",
        event_metadata={"fields": list(update_data.keys())},
    ))
    await session.commit()
    await session.refresh(packet)

    document_count, total_pages, completed_count, failed_count = await _packet_summary(session, packet.id)
    return serialize_packet(packet, document_count, total_pages, completed_count, failed_count)


@router.delete("/{packet_id}")
async def delete_packet(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    documents_result = await session.execute(
        select(Document).where(Document.packet_id == packet_id)
    )
    documents = documents_result.scalars().all()

    removed_files = []
    for document in documents:
        removed_files.extend(await cleanup_document_files(session, document))

    session.add(AuditEvent(
        event_type=AuditEventType.PACKET_DELETED,
        user_id="system",
        event_metadata={"packet_id": str(packet.id), "packet_name": packet.name, "document_count": len(documents)},
    ))

    await session.delete(packet)
    await session.commit()

    final_dir = get_settings().final_path / str(packet_id)
    if final_dir.exists():
        shutil.rmtree(final_dir, ignore_errors=True)

    return {"message": f"Packet {packet_id} deleted", "files_removed": removed_files}


@router.post("/{packet_id}/reorder")
async def reorder_documents(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")
    return {"message": "Reorder endpoint moved to /documents/{packet_id}/{document_id}/reorder"}