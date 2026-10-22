from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

from app.database import get_session
from app.domain.packet import Packet
from app.domain.document import Document
from app.domain.privilege import PrivilegeDecision, PrivilegeStatus, PrivilegeCategory
from app.domain.bates import BatesAssignment
from app.domain.audit import AuditEvent, AuditEventType
from app.time import utc_now

router = APIRouter()


class PrivilegeDecisionRequest(BaseModel):
    status: PrivilegeStatus
    category: Optional[PrivilegeCategory] = None
    reason: Optional[str] = None
    reviewer: str


class PrivilegeDecisionResponse(BaseModel):
    id: str
    document_id: str
    status: str
    category: Optional[str]
    reason: Optional[str]
    bates_start: Optional[str]
    bates_end: Optional[str]
    reviewer: str
    decided_at: Optional[datetime]


@router.get("/{packet_id}")
async def get_privilege_decisions(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(PrivilegeDecision).where(PrivilegeDecision.packet_id == packet_id)
    )
    decisions = result.scalars().all()

    return [
        PrivilegeDecisionResponse(
            id=str(d.id),
            document_id=str(d.document_id),
            status=d.status.value,
            category=d.category.value if d.category else None,
            reason=d.reason,
            bates_start=d.bates_start,
            bates_end=d.bates_end,
            reviewer=d.reviewer,
            decided_at=d.decided_at,
        )
        for d in decisions
    ]


@router.post("/{packet_id}/{document_id}")
async def mark_privilege(
    packet_id: UUID,
    document_id: UUID,
    request: PrivilegeDecisionRequest,
    session: AsyncSession = Depends(get_session),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    if request.status == PrivilegeStatus.PRIVILEGED and not request.reason:
        raise HTTPException(status_code=400, detail="Privilege reason is required for privileged documents")

    result = await session.execute(
        select(PrivilegeDecision).where(
            PrivilegeDecision.packet_id == packet_id,
            PrivilegeDecision.document_id == document_id,
        )
    )
    existing = result.scalars().first()

    bates_assignments = await session.execute(
        select(BatesAssignment).where(
            BatesAssignment.packet_id == packet_id,
            BatesAssignment.document_id == document_id,
        ).order_by(BatesAssignment.bates_number)
    )
    bates_list = bates_assignments.scalars().all()
    bates_start = bates_list[0].bates_label if bates_list else None
    bates_end = bates_list[-1].bates_label if bates_list else None

    if existing:
        existing.status = request.status
        existing.category = request.category
        existing.reason = request.reason
        existing.bates_start = bates_start
        existing.bates_end = bates_end
        existing.reviewer = request.reviewer
        existing.decided_at = utc_now()
        existing.updated_at = utc_now()
        decision = existing
    else:
        decision = PrivilegeDecision(
            packet_id=packet_id,
            document_id=document_id,
            status=request.status,
            category=request.category,
            reason=request.reason,
            bates_start=bates_start,
            bates_end=bates_end,
            reviewer=request.reviewer,
            decided_at=utc_now(),
        )
        session.add(decision)

    audit_event = AuditEvent(
        packet_id=packet_id,
        document_id=document_id,
        event_type=AuditEventType.PRIVILEGE_MARKED,
        user_id=request.reviewer,
        event_metadata={
            "action": "updated" if existing else "created",
            "status": request.status.value,
            "category": request.category.value if request.category else None,
            "reason": request.reason,
        },
    )
    session.add(audit_event)

    await session.commit()
    await session.refresh(decision)

    return PrivilegeDecisionResponse(
        id=str(decision.id),
        document_id=str(decision.document_id),
        status=decision.status.value,
        category=decision.category.value if decision.category else None,
        reason=decision.reason,
        bates_start=decision.bates_start,
        bates_end=decision.bates_end,
        reviewer=decision.reviewer,
        decided_at=decision.decided_at,
    )


@router.patch("/{packet_id}/{document_id}")
async def update_privilege(
    packet_id: UUID,
    document_id: UUID,
    request: PrivilegeDecisionRequest,
    session: AsyncSession = Depends(get_session),
):
    return await mark_privilege(packet_id, document_id, request, session)


@router.get("/{packet_id}/log")
async def generate_privilege_log(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(PrivilegeDecision, Document)
        .join(Document, PrivilegeDecision.document_id == Document.id)
        .where(PrivilegeDecision.packet_id == packet_id)
        .where(PrivilegeDecision.status == PrivilegeStatus.PRIVILEGED)
    )
    privileged_docs = result.fetchall()

    log_entries = []
    for decision, document in privileged_docs:
        bates_assignments = await session.execute(
            select(BatesAssignment).where(
                BatesAssignment.packet_id == packet_id,
                BatesAssignment.document_id == document.id,
            ).order_by(BatesAssignment.bates_number)
        )
        bates_list = bates_assignments.scalars().all()
        bates_start = bates_list[0].bates_label if bates_list else "N/A"
        bates_end = bates_list[-1].bates_label if bates_list else "N/A"

        log_entries.append({
            "document_id": str(document.id),
            "filename": document.original_filename,
            "bates_range": f"{bates_start} - {bates_end}",
            "privilege_category": decision.category.value if decision.category else "other",
            "reason": decision.reason,
            "reviewer": decision.reviewer,
            "decided_at": decision.decided_at.isoformat() if decision.decided_at else None,
            "page_count": document.page_count,
        })

    return {
        "packet_id": packet_id,
        "packet_name": packet.name,
        "generated_at": utc_now().isoformat(),
        "total_privileged_documents": len(log_entries),
        "entries": log_entries,
    }