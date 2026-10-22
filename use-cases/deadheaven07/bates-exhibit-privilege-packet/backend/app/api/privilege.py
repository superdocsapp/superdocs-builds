from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.bates import BatesAssignment
from app.domain.document import Document
from app.domain.packet import Packet
from app.domain.privilege import PrivilegeCategory, PrivilegeDecision, PrivilegeStatus
from app.services.superdocs_integration import SuperDocsIntegrationService, get_superdocs_service
from app.services.superdocs_intelligence import SuperDocsIntelligenceService
from app.time import utc_now

router = APIRouter()


def _new_intelligence() -> "SuperDocsIntelligenceService":
    from app.services.superdocs_intelligence import new_intelligence_service
    return new_intelligence_service()


class PrivilegeDecisionRequest(BaseModel):
    status: PrivilegeStatus
    category: PrivilegeCategory | None = None
    reason: str | None = None
    reviewer: str


class PrivilegeDecisionResponse(BaseModel):
    id: str
    document_id: str
    status: str
    category: str | None
    reason: str | None
    bates_start: str | None
    bates_end: str | None
    reviewer: str
    decided_at: datetime | None


class PrivilegeAnalysisRequest(BaseModel):
    force_reanalyze: bool = False


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
            reviewer=d.reviewer or "unknown",
            decided_at=d.decided_at,
        )
        for d in decisions
    ]


@router.post("/{packet_id}/{document_id}/analyze-privilege")
async def analyze_privilege(
    packet_id: UUID,
    document_id: UUID,
    request: PrivilegeAnalysisRequest,
    session: AsyncSession = Depends(get_session),
    superdocs: "SuperDocsIntegrationService" = Depends(get_superdocs_service),
):
    """Analyze document for privilege using SuperDocs."""
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.processing_status != "completed":
        raise HTTPException(
            status_code=400, detail="Document must be fully processed before privilege analysis"
        )

    result = await superdocs.analyze_privilege(session, document)

    return {
        "document_id": str(document.id),
        "is_privileged": result.is_privileged,
        "category": result.category.value if result.category else None,
        "reason": result.reason,
        "confidence": result.confidence,
        "key_phrases": result.key_phrases,
    }


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
        raise HTTPException(
            status_code=400, detail="Privilege reason is required for privileged documents"
        )

    result = await session.execute(
        select(PrivilegeDecision).where(
            PrivilegeDecision.packet_id == packet_id,
            PrivilegeDecision.document_id == document_id,
        )
    )
    existing = result.scalars().first()

    bates_assignments = await session.execute(
        select(BatesAssignment)
        .where(
            BatesAssignment.packet_id == packet_id,
            BatesAssignment.document_id == document_id,
        )
        .order_by(BatesAssignment.bates_number)
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

    synced = False
    if decision.superdocs_change_id:
        superdocs = _new_intelligence()
        try:
            syncer = getattr(superdocs, "sync_approval", None)
            if syncer is not None:
                approved = request.status != PrivilegeStatus.PRIVILEGED
                await syncer(
                    document=document,
                    job_id=f"privilege:{document_id}",
                    approved=approved,
                    changes=[{"change_id": decision.superdocs_change_id, "operation": "replace"}],
                )
                synced = True
        except Exception as exc:  # noqa: BLE001
            session.add(
                AuditEvent(
                    packet_id=packet_id,
                    document_id=document_id,
                    event_type=AuditEventType.AI_ANALYSIS_FAILED,
                    user_id="system",
                    event_metadata={"error": str(exc), "step": "privilege_sync"},
                )
            )

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
            "superdocs_synced": synced,
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
        reviewer=decision.reviewer or "unknown",
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
            select(BatesAssignment)
            .where(
                BatesAssignment.packet_id == packet_id,
                BatesAssignment.document_id == document.id,
            )
            .order_by(BatesAssignment.bates_number)
        )
        bates_list = bates_assignments.scalars().all()
        bates_start = bates_list[0].bates_label if bates_list else "N/A"
        bates_end = bates_list[-1].bates_label if bates_list else "N/A"

        log_entries.append(
            {
                "document_id": str(document.id),
                "filename": document.original_filename,
                "bates_range": f"{bates_start} - {bates_end}",
                "privilege_category": decision.category.value if decision.category else "other",
                "reason": decision.reason,
                "reviewer": decision.reviewer,
                "decided_at": decision.decided_at.isoformat() if decision.decided_at else None,
                "page_count": document.page_count,
            }
        )

    return {
        "packet_id": packet_id,
        "packet_name": packet.name,
        "generated_at": utc_now().isoformat(),
        "total_privileged_documents": len(log_entries),
        "entries": log_entries,
    }
