from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.packet import Packet
from app.services.bates_assignment import BatesAssignmentService, format_bates_number

router = APIRouter()


@router.post("/{packet_id}/assign")
async def assign_bates(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    service = BatesAssignmentService()
    try:
        assignments = await service.assign_bates(session, packet_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    if assignments:
        session.add(
            AuditEvent(
                packet_id=packet_id,
                event_type=AuditEventType.BATES_ASSIGNED,
                user_id="system",
                event_metadata={
                    "count": len(assignments),
                    "bates_start": assignments[0].bates_label,
                    "bates_end": assignments[-1].bates_label,
                },
            )
        )
        await session.commit()

    return {
        "message": f"Bates numbers assigned to {len(assignments)} pages",
        "assignments": [
            {
                "document_id": str(a.document_id),
                "page_number": a.page_number,
                "bates_number": a.bates_number,
                "bates_label": a.bates_label,
            }
            for a in assignments
        ],
    }


@router.get("/{packet_id}")
async def get_bates_assignments(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    service = BatesAssignmentService()
    assignments = await service.get_bates_assignments(session, packet_id)

    return {
        "packet_id": packet_id,
        "total_assignments": len(assignments),
        "assignments": [
            {
                "document_id": str(a.document_id),
                "page_number": a.page_number,
                "bates_number": a.bates_number,
                "bates_label": a.bates_label,
            }
            for a in assignments
        ],
    }


@router.get("/{packet_id}/preview")
async def preview_bates(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    service = BatesAssignmentService()
    preview = await service.preview_bates(session, packet_id)

    completed = [p for p in preview if not p["skipped"]]
    if completed:
        start_label = completed[0]["bates_start"]
        end_label = completed[-1]["bates_end"]
    else:
        start_label = None
        end_label = None

    return {
        "packet_id": packet_id,
        "prefix": packet.bates_prefix,
        "start_label": start_label,
        "end_label": end_label,
        "documents": preview,
    }


@router.post("/{packet_id}/finalize")
async def finalize_bates(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    service = BatesAssignmentService()
    assignments = await service.get_bates_assignments(session, packet_id)
    if not assignments:
        raise HTTPException(status_code=400, detail="No Bates assignments exist. Run assign first.")

    highest = max(a.bates_number for a in assignments)
    return {
        "message": "Bates assignments finalized",
        "packet_id": packet_id,
        "last_bates_number": highest,
        "last_bates_label": format_bates_number(packet.bates_prefix, highest, packet.bates_padding),
        "total_assignments": len(assignments),
    }
