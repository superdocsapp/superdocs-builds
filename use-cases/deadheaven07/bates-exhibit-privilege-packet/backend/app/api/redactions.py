from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session_maker, get_session
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.document import Document, ProcessingStatus
from app.domain.packet import Packet
from app.domain.redaction import RedactionApproval, RedactionCandidate, RedactionStatus
from app.services.superdocs_integration import SuperDocsIntegrationService, get_superdocs_service
from app.services.superdocs_port import PIICategory
from app.time import utc_now as _now

router = APIRouter()


class RedactionApprovalRequest(BaseModel):
    status: RedactionStatus
    approver: str


class ApplyRedactionsRequest(BaseModel):
    document_ids: list[UUID]


class DetectRedactionsRequest(BaseModel):
    categories: list[str] | None = None


def _serialize_candidate(candidate: RedactionCandidate, document_name: str | None = None) -> dict:
    data = {
        "id": str(candidate.id),
        "document_id": str(candidate.document_id),
        "page_number": candidate.page_number,
        "category": candidate.category.value,
        "matched_text": candidate.matched_text,
        "context_before": candidate.context_before,
        "context_after": candidate.context_after,
        "coordinates": {
            "x0": candidate.x0,
            "y0": candidate.y0,
            "x1": candidate.x1,
            "y1": candidate.y1,
        },
        "status": candidate.status.value,
        "reason": candidate.reason,
        "proposed_at": candidate.proposed_at.isoformat() if candidate.proposed_at else None,
        "proposed_by": candidate.proposed_by,
        "approval": {
            "status": candidate.approval.status.value if candidate.approval else None,
            "approver": candidate.approval.approver if candidate.approval else None,
            "approved_at": candidate.approval.approved_at.isoformat()
            if candidate.approval and candidate.approval.approved_at
            else None,
            "applied_at": candidate.approval.applied_at.isoformat()
            if candidate.approval and candidate.approval.applied_at
            else None,
            "verified_at": candidate.approval.verified_at.isoformat()
            if candidate.approval and candidate.approval.verified_at
            else None,
            "verification_passed": candidate.approval.verification_passed
            if candidate.approval
            else None,
        }
        if candidate.approval
        else None,
    }
    if document_name is not None:
        data["document_name"] = document_name
    return data


@router.post("/{packet_id}/detect")
async def detect_redactions(
    packet_id: UUID,
    request: DetectRedactionsRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsIntegrationService = Depends(get_superdocs_service),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(Document).where(
            Document.packet_id == packet_id,
            Document.processing_status == ProcessingStatus.COMPLETED,
        )
    )
    documents = result.scalars().all()

    categories = None
    if request.categories:
        categories = [PIICategory(c) for c in request.categories]

    for document in documents:
        background_tasks.add_task(detect_document_redactions, superdocs, document.id, categories)

    return {
        "message": f"Redaction detection started for {len(documents)} documents",
        "documents_queued": len(documents),
    }


async def detect_document_redactions(
    superdocs: SuperDocsIntegrationService,
    document_id: UUID,
    categories: list[PIICategory] | None = None,
):
    async with async_session_maker() as bg_session:
        document = await bg_session.get(Document, document_id)
        if not document:
            return

        pii_result = await superdocs.detect_pii(bg_session, document, categories)
        candidates = await superdocs.create_redaction_candidates(
            bg_session, document, pii_result, categories
        )
        created, skipped = await superdocs.reconcile_candidates(bg_session, document, candidates)
        for candidate in created:
            bg_session.add(candidate)

        audit_event = AuditEvent(
            packet_id=document.packet_id,
            document_id=document.id,
            event_type=AuditEventType.REDACTION_PROPOSED,
            user_id="system",
            event_metadata={
                "candidates_found": len(candidates),
                "candidates_created": len(created),
                "candidates_skipped": skipped,
            },
        )
        bg_session.add(audit_event)
        await bg_session.commit()


@router.get("/{packet_id}")
async def get_redaction_candidates(packet_id: UUID, session: AsyncSession = Depends(get_session)):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(RedactionCandidate, Document)
        .join(Document, RedactionCandidate.document_id == Document.id)
        .where(Document.packet_id == packet_id)
        .options(selectinload(RedactionCandidate.approval))
    )
    candidates = result.fetchall()

    return [
        _serialize_candidate(candidate, document.original_filename)
        for candidate, document in candidates
    ]


@router.get("/{packet_id}/{document_id}")
async def get_document_redactions(
    packet_id: UUID, document_id: UUID, session: AsyncSession = Depends(get_session)
):
    document = await session.get(Document, document_id)
    if not document or document.packet_id != packet_id:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await session.execute(
        select(RedactionCandidate)
        .where(RedactionCandidate.document_id == document_id)
        .options(
            selectinload(RedactionCandidate.approval),
        )
    )
    candidates = result.scalars().all()

    return [_serialize_candidate(candidate) for candidate in candidates]


@router.post("/{redaction_id}/approve")
async def approve_redaction(
    redaction_id: UUID,
    request: RedactionApprovalRequest,
    session: AsyncSession = Depends(get_session),
):
    candidate = await session.get(
        RedactionCandidate,
        redaction_id,
        options=(
            selectinload(RedactionCandidate.approval),
            selectinload(RedactionCandidate.document),
        ),
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Redaction candidate not found")

    if candidate.status not in [RedactionStatus.PROPOSED, RedactionStatus.PENDING_APPROVAL]:
        raise HTTPException(
            status_code=400, detail="Redaction is not in a state that can be approved"
        )

    if request.status == RedactionStatus.APPROVED:
        candidate.status = RedactionStatus.APPROVED
        approval = RedactionApproval(
            candidate_id=candidate.id,
            status=RedactionStatus.APPROVED,
            approver=request.approver,
        )
        session.add(approval)
    else:
        candidate.status = RedactionStatus.REJECTED
        approval = RedactionApproval(
            candidate_id=candidate.id,
            status=RedactionStatus.REJECTED,
            approver=request.approver,
        )
        session.add(approval)

    audit_event = AuditEvent(
        packet_id=candidate.document.packet_id if candidate.document else None,
        document_id=candidate.document_id,
        event_type=AuditEventType.REDACTION_APPROVED
        if request.status == RedactionStatus.APPROVED
        else AuditEventType.REDACTION_REJECTED,
        user_id=request.approver,
        event_metadata={"candidate_id": str(candidate.id)},
    )
    session.add(audit_event)

    await session.commit()

    return {"message": f"Redaction {request.status.value}", "candidate_id": str(candidate.id)}


@router.post("/{redaction_id}/reject")
async def reject_redaction(
    redaction_id: UUID,
    request: RedactionApprovalRequest,
    session: AsyncSession = Depends(get_session),
):
    request.status = RedactionStatus.REJECTED
    return await approve_redaction(redaction_id, request, session)


@router.post("/{redaction_id}/apply")
async def apply_redaction(
    redaction_id: UUID,
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsIntegrationService = Depends(get_superdocs_service),
):
    candidate = await session.get(
        RedactionCandidate,
        redaction_id,
        options=(
            selectinload(RedactionCandidate.approval),
            selectinload(RedactionCandidate.document),
        ),
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Redaction candidate not found")

    if not candidate.approval or candidate.approval.status != RedactionStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Redaction must be approved before applying")

    if candidate.status == RedactionStatus.APPLIED:
        raise HTTPException(status_code=400, detail="Redaction already applied")

    # Apply redaction via SuperDocs
    batch = await _appliable_candidates(session, candidate.document_id)

    result = await superdocs.apply_redactions(session, candidate.document, batch)
    if not result or result.status != "completed":
        error = result.error if result else "Unknown error"
        candidate.status = RedactionStatus.FAILED
        session.add(
            AuditEvent(
                packet_id=candidate.document.packet_id,
                document_id=candidate.document_id,
                event_type=AuditEventType.REDACTION_FAILED,
                user_id=candidate.approval.approver if candidate.approval else "system",
                event_metadata={"candidate_id": str(candidate.id), "error": error},
            )
        )
        await session.commit()
        raise HTTPException(status_code=422, detail=f"Redaction apply failed: {error}")

    # Mark all candidates in batch as applied
    for c in await _appliable_candidates(session, candidate.document_id):
        c.status = RedactionStatus.APPLIED
        if c.approval:
            c.approval.applied_at = _now()
            c.approval.applied_by = c.approval.approver

    session.add(
        AuditEvent(
            packet_id=candidate.document.packet_id,
            document_id=candidate.document_id,
            event_type=AuditEventType.REDACTION_APPLIED,
            user_id=candidate.approval.approver if candidate.approval else "system",
            event_metadata={"candidate_id": str(candidate.id), "job_id": result.job_id},
        )
    )

    await session.commit()

    return {
        "message": "Redaction applied",
        "candidate_id": str(candidate.id),
        "job_id": result.job_id,
        "status": result.status,
    }


@router.post("/{packet_id}/apply-all")
async def apply_all_approved_redactions(
    packet_id: UUID,
    request: ApplyRedactionsRequest,
    session: AsyncSession = Depends(get_session),
    superdocs: SuperDocsIntegrationService = Depends(get_superdocs_service),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    results = []

    for document_id in request.document_ids:
        document = await session.get(Document, document_id)
        if not document or document.packet_id != packet_id:
            continue

        batch = await _appliable_candidates(session, document_id)
        if not batch:
            continue

        result = await superdocs.apply_redactions(session, document, batch)

        failed = []
        for candidate in batch:
            if result.status != "completed":
                candidate.status = RedactionStatus.FAILED
                failed.append(
                    {
                        "candidate_id": str(candidate.id),
                        "error": result.error if result else "Unknown error",
                    }
                )
            else:
                candidate.status = RedactionStatus.APPLIED
                if candidate.approval:
                    candidate.approval.applied_at = _now()
                    candidate.approval.applied_by = candidate.approval.approver

        for candidate in batch:
            if candidate.status == RedactionStatus.APPLIED:
                session.add(
                    AuditEvent(
                        packet_id=packet_id,
                        document_id=document_id,
                        event_type=AuditEventType.REDACTION_APPLIED,
                        user_id=candidate.approval.approver if candidate.approval else "system",
                        event_metadata={"candidate_id": str(candidate.id), "job_id": result.job_id},
                    )
                )

        results.append(
            {
                "document_id": str(document_id),
                "candidates_applied": len(
                    [c for c in batch if c.status == RedactionStatus.APPLIED]
                ),
                "candidates_failed": len(failed),
                "failures": failed,
                "job_id": result.job_id,
                "status": result.status,
            }
        )

    await session.commit()

    return {"results": results}


async def _appliable_candidates(
    session: AsyncSession, document_id: UUID
) -> list[RedactionCandidate]:
    result = await session.execute(
        select(RedactionCandidate)
        .where(
            RedactionCandidate.document_id == document_id,
            RedactionCandidate.status.in_([RedactionStatus.APPROVED, RedactionStatus.APPLIED]),
        )
        .options(selectinload(RedactionCandidate.approval))
    )
    return list(result.scalars().all())
