from collections.abc import Sequence
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session_maker, get_session
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.document import Document, ProcessingStatus
from app.domain.packet import Packet
from app.domain.redaction import RedactionApproval, RedactionCandidate, RedactionStatus
from app.services.redaction import RedactionApplicationService, RedactionDetectionService
from app.services.superdocs_intelligence import SuperDocsIntelligenceService
from app.services.superdocs_port import PIICategory

router = APIRouter()


def _new_detection_service() -> RedactionDetectionService:
    return RedactionDetectionService()


def _new_application_service() -> RedactionApplicationService:
    return RedactionApplicationService()


def _new_intelligence() -> SuperDocsIntelligenceService:
    return SuperDocsIntelligenceService()


class RedactionApprovalRequest(BaseModel):
    status: RedactionStatus
    approver: str


class ApplyRedactionsRequest(BaseModel):
    document_ids: list[UUID]


class DetectRedactionsRequest(BaseModel):
    categories: list[str] | None = None


class BatchApprovalRequest(BaseModel):
    redaction_ids: list[UUID]
    status: RedactionStatus = RedactionStatus.APPROVED
    approver: str


def _serialize_candidate(candidate: RedactionCandidate, document_name: str | None = None) -> dict:
    category_val = candidate.category.value if hasattr(candidate.category, "value") else str(candidate.category)
    status_val = candidate.status.value if hasattr(candidate.status, "value") else str(candidate.status)

    approval_dict = None
    if candidate.approval:
        app_status = (
            candidate.approval.status.value
            if hasattr(candidate.approval.status, "value")
            else str(candidate.approval.status)
        )
        approval_dict = {
            "status": app_status,
            "approver": candidate.approval.approver,
            "approved_at": (
                candidate.approval.approved_at.isoformat()
                if candidate.approval.approved_at
                else None
            ),
            "applied_at": (
                candidate.approval.applied_at.isoformat()
                if candidate.approval.applied_at
                else None
            ),
            "verified_at": (
                candidate.approval.verified_at.isoformat()
                if candidate.approval.verified_at
                else None
            ),
            "verification_passed": candidate.approval.verification_passed,
        }

    data = {
        "id": str(candidate.id),
        "document_id": str(candidate.document_id),
        "page_number": candidate.page_number,
        "category": category_val,
        "matched_text": candidate.matched_text,
        "context_before": candidate.context_before,
        "context_after": candidate.context_after,
        "coordinates": {
            "x0": candidate.x0,
            "y0": candidate.y0,
            "x1": candidate.x1,
            "y1": candidate.y1,
        },
        "status": status_val,
        "reason": candidate.reason,
        "proposed_at": candidate.proposed_at.isoformat() if candidate.proposed_at else None,
        "proposed_by": candidate.proposed_by,
        "superdocs_change_id": candidate.superdocs_change_id,
        "approval": approval_dict,
    }
    if document_name is not None:
        data["document_name"] = document_name
    return data


# ---------------------------------------------------------------------- #
# Detection / intelligence
# ---------------------------------------------------------------------- #
@router.post("/{packet_id}/detect")
async def detect_redactions(
    packet_id: UUID,
    background_tasks: BackgroundTasks,
    request: DetectRedactionsRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Detect PII via the primary intelligence path (SuperDocs async chat,
    ask_every_time) with automatic degradation to the labeled local fallback
    when SuperDocs is unavailable."""
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(Document).where(
            Document.packet_id == packet_id,
            Document.processing_status != ProcessingStatus.FAILED,
        )
    )
    documents = result.scalars().all()

    categories: list[PIICategory] | None = None
    if request and request.categories:
        valid_cats: list[PIICategory] = []
        for c in request.categories:
            try:
                valid_cats.append(PIICategory(c.lower()))
            except (ValueError, KeyError):
                pass
        categories = valid_cats or None

    for document in documents:
        background_tasks.add_task(detect_document_redactions, document.id, categories)

    return {
        "message": f"Redaction detection started for {len(documents)} documents",
        "documents_queued": len(documents),
    }


@router.post("/{packet_id}/analyze")
async def analyze_packet_intelligence(
    packet_id: UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Run the SuperDocs intelligence pass (PII + privilege proposals) over
    every completed document. Each proposal surfaces as a native SuperDocs
    ``pending_change`` mirrored to a DB candidate awaiting human review."""
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    result = await session.execute(
        select(Document).where(
            Document.packet_id == packet_id,
            Document.processing_status != ProcessingStatus.FAILED,
        )
    )
    documents = result.scalars().all()

    for document in documents:
        background_tasks.add_task(run_intelligence_pass, document.id)

    return {
        "message": f"SuperDocs intelligence analysis started for {len(documents)} documents",
        "documents_queued": len(documents),
    }


async def run_intelligence_pass(
    document_id: UUID,
    categories: list[PIICategory] | None = None,
):
    detection = _new_detection_service()
    async with async_session_maker() as bg_session:
        document = await bg_session.get(Document, document_id)
        if not document:
            return

        siblings = []
        try:
            siblings_result = await bg_session.execute(
                select(Document)
                .where(
                    Document.packet_id == document.packet_id,
                    Document.id != document.id,
                    Document.processing_status == ProcessingStatus.COMPLETED,
                )
                .order_by(Document.display_order)
            )
            siblings = list(siblings_result.scalars().all())
        except Exception:  # noqa: BLE001
            pass

        try:
            pii_result = await detection.detect_pii_in_document(
                bg_session, document.id, categories=categories, siblings=siblings
            )
        except Exception as e:  # noqa: BLE001
            bg_session.add(
                AuditEvent(
                    packet_id=document.packet_id,
                    document_id=document.id,
                    event_type=AuditEventType.REDACTION_FAILED,
                    user_id="system",
                    event_metadata={"error": str(e)},
                )
            )
            await bg_session.commit()
            return

        candidates = await detection.create_redaction_candidates(bg_session, document, pii_result)
        created, skipped = await detection.reconcile_candidates(bg_session, document.id, candidates)
        for candidate in created:
            bg_session.add(candidate)

        bg_session.add(
            AuditEvent(
                packet_id=document.packet_id,
                document_id=document.id,
                event_type=AuditEventType.REDACTION_PROPOSED,
                user_id="system",
                event_metadata={
                    "candidates_found": len(candidates),
                    "candidates_created": len(created),
                    "candidates_skipped": skipped,
                    "intelligence_source": pii_result.session_id
                    and "superdocs"
                    or "local_fallback",
                },
            )
        )
        await bg_session.commit()


async def detect_document_redactions(
    document_id: UUID,
    categories: list[PIICategory] | None = None,
):
    """Background task for the /detect endpoint with category forwarding."""
    await run_intelligence_pass(document_id, categories=categories)


# ---------------------------------------------------------------------- #
# Listing
# ---------------------------------------------------------------------- #
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


# ---------------------------------------------------------------------- #
# Human review (one-by-one and batch)
# ---------------------------------------------------------------------- #
@router.post("/{redaction_id}/approve")
async def approve_redaction(
    redaction_id: UUID,
    request: RedactionApprovalRequest,
    session: AsyncSession = Depends(get_session),
):
    return await _decide_redaction(redaction_id, request, session)


@router.post("/{redaction_id}/reject")
async def reject_redaction(
    redaction_id: UUID,
    request: RedactionApprovalRequest,
    session: AsyncSession = Depends(get_session),
):
    request.status = RedactionStatus.REJECTED
    return await _decide_redaction(redaction_id, request, session)


async def _decide_redaction(
    redaction_id: UUID,
    request: RedactionApprovalRequest,
    session: AsyncSession,
) -> dict:
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

    target_status = request.status
    candidate.status = target_status
    if candidate.approval:
        candidate.approval.status = target_status
        candidate.approval.approver = request.approver
    else:
        approval = RedactionApproval(
            candidate_id=candidate.id,
            status=target_status,
            approver=request.approver,
        )
        session.add(approval)

    synced = False
    if candidate.superdocs_change_id and candidate.document:
        superdocs = _new_intelligence()
        try:
            syncer = getattr(superdocs, "sync_approval", None)
            if syncer is not None:
                await syncer(
                    document=candidate.document,
                    job_id=f"single:{candidate.document_id}",
                    approved=request.status == RedactionStatus.APPROVED,
                    changes=[
                        {
                            "change_id": candidate.superdocs_change_id,
                            "operation": "replace",
                        }
                    ],
                )
                synced = True
        except Exception as exc:  # noqa: BLE001
            session.add(
                AuditEvent(
                    packet_id=candidate.document.packet_id if candidate.document else None,
                    document_id=candidate.document_id,
                    event_type=AuditEventType.AI_ANALYSIS_FAILED,
                    user_id="system",
                    event_metadata={
                        "error": str(exc),
                        "step": "single_approval_sync",
                    },
                )
            )

    session.add(
        AuditEvent(
            packet_id=candidate.document.packet_id if candidate.document else None,
            document_id=candidate.document_id,
            event_type=AuditEventType.REDACTION_APPROVED
            if request.status == RedactionStatus.APPROVED
            else AuditEventType.REDACTION_REJECTED,
            user_id=request.approver,
            event_metadata={
                "candidate_id": str(candidate.id),
                "superdocs_change_id": candidate.superdocs_change_id,
                "superdocs_synced": synced,
            },
        )
    )

    await session.commit()

    return {"message": f"Redaction {request.status.value}", "candidate_id": str(candidate.id)}


@router.post("/{packet_id}/approve-batch")
async def approve_redaction_batch(
    packet_id: UUID,
    request: BatchApprovalRequest,
    session: AsyncSession = Depends(get_session),
):
    """Human batch approval: approve or reject multiple proposals at once,
    then sync the decision back to the SuperDocs pending_change job."""
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    candidates = (
        (
            await session.execute(
                select(RedactionCandidate)
                .where(
                    RedactionCandidate.id.in_(request.redaction_ids),
                    RedactionCandidate.document.has(Document.packet_id == packet_id),
                )
                .options(
                    selectinload(RedactionCandidate.approval),
                    selectinload(RedactionCandidate.document),
                )
            )
        )
        .scalars()
        .all()
    )

    if len(candidates) != len(request.redaction_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more redaction candidates not found in this packet",
        )

    target_status = request.status
    for candidate in candidates:
        if candidate.status not in [RedactionStatus.PROPOSED, RedactionStatus.PENDING_APPROVAL]:
            raise HTTPException(
                status_code=400,
                detail=f"Redaction {candidate.id} is not in a reviewable state",
            )
        candidate.status = target_status
        if candidate.approval:
            candidate.approval.status = target_status
            candidate.approval.approver = request.approver
        else:
            session.add(
                RedactionApproval(
                    candidate_id=candidate.id,
                    status=target_status,
                    approver=request.approver,
                )
            )
        session.add(
            AuditEvent(
                packet_id=packet_id,
                document_id=candidate.document_id,
                event_type=AuditEventType.REDACTION_APPROVED
                if target_status == RedactionStatus.APPROVED
                else AuditEventType.REDACTION_REJECTED,
                user_id=request.approver,
                event_metadata={
                    "candidate_id": str(candidate.id),
                    "batch": True,
                    "superdocs_change_id": candidate.superdocs_change_id,
                },
            )
        )

    # Sync to SuperDocs (job-level) when proposals came from the primary layer.
    # Best-effort: the human decision is authoritative locally; platform sync
    # failures are surfaced in the audit trail, never block the review.
    superdocs = _new_intelligence()
    synced = False
    if any(c.superdocs_change_id for c in candidates):
        try:
            syncer = getattr(superdocs, "sync_approval", None)
            if syncer is not None:
                await syncer(
                    document=candidates[0].document,
                    job_id=_job_key(candidates),
                    approved=target_status == RedactionStatus.APPROVED,
                    changes=[
                        {
                            "change_id": c.superdocs_change_id,
                            "operation": "replace",
                        }
                        for c in candidates
                        if c.superdocs_change_id
                    ],
                )
                synced = True
        except Exception as exc:  # noqa: BLE001
            session.add(
                AuditEvent(
                    packet_id=packet_id,
                    event_type=AuditEventType.AI_ANALYSIS_FAILED,
                    user_id="system",
                    event_metadata={
                        "error": str(exc),
                        "step": "approval_sync",
                    },
                )
            )

    await session.commit()
    return {
        "message": f"{len(candidates)} redactions {target_status.value}",
        "approved_count": len(candidates),
        "superdocs_synced": synced,
    }


def _job_key(candidates: Sequence[RedactionCandidate] | list[RedactionCandidate]) -> str:
    # Group changes per document session/job. The native change payload only
    # carries change_id; the job is derived from the last intelligence pass.
    return "batch:" + ",".join(sorted(str(c.document_id) for c in candidates))


# ---------------------------------------------------------------------- #
# Application
# ---------------------------------------------------------------------- #
@router.post("/{redaction_id}/apply")
async def apply_redaction(
    redaction_id: UUID,
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

    if not candidate.approval or candidate.approval.status != RedactionStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Redaction must be approved before applying")

    if candidate.status == RedactionStatus.APPLIED:
        raise HTTPException(status_code=400, detail="Redaction already applied")

    application = _new_application_service()
    batch = await _appliable_candidates(session, candidate.document_id)
    results = await application.apply_redactions(session, candidate.document, batch)

    candidate_result = results.get(str(candidate.id), {})
    if not candidate_result.get("applied"):
        candidate.status = RedactionStatus.FAILED
        session.add(
            AuditEvent(
                packet_id=candidate.document.packet_id,
                document_id=candidate.document_id,
                event_type=AuditEventType.REDACTION_FAILED,
                user_id=candidate.approval.approver if candidate.approval else "system",
                event_metadata={
                    "candidate_id": str(candidate.id),
                    "error": candidate_result.get("error", "unknown"),
                },
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=422,
            detail=f"Redaction apply failed: {candidate_result.get('error', 'unknown')}",
        )

    _finalize_applied_batch(session, batch, results)

    session.add(
        AuditEvent(
            packet_id=candidate.document.packet_id,
            document_id=candidate.document_id,
            event_type=AuditEventType.REDACTION_APPLIED,
            user_id=candidate.approval.approver if candidate.approval else "system",
            event_metadata={
                "candidate_id": str(candidate.id),
                "job_id": candidate_result.get("job_id"),
            },
        )
    )
    for c in batch:
        entry = results.get(str(c.id), {})
        if entry.get("verified"):
            session.add(
                AuditEvent(
                    packet_id=candidate.document.packet_id,
                    document_id=candidate.document_id,
                    event_type=AuditEventType.REDACTION_VERIFIED,
                    user_id=candidate.approval.approver if candidate.approval else "system",
                    event_metadata={
                        "candidate_id": str(c.id),
                        "text_still_present": entry.get("text_still_present", False),
                    },
                )
            )

    await session.commit()

    return {
        "status": "completed",
        "message": "Redaction applied",
        "candidate_id": str(candidate.id),
        "verified": bool(candidate_result.get("verified")),
        "job_id": candidate_result.get("job_id"),
    }


@router.post("/{packet_id}/apply-all")
async def apply_all_approved_redactions(
    packet_id: UUID,
    request: ApplyRedactionsRequest,
    session: AsyncSession = Depends(get_session),
):
    packet = await session.get(Packet, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Packet not found")

    application = _new_application_service()
    results = []

    for document_id in request.document_ids:
        document = await session.get(Document, document_id)
        if not document or document.packet_id != packet_id:
            continue

        batch = await _appliable_candidates(session, document_id)
        if not batch:
            continue

        apply_results = await application.apply_redactions(session, document, batch)
        _finalize_applied_batch(session, batch, apply_results)

        failed = []
        for candidate in batch:
            entry = apply_results.get(str(candidate.id), {})
            if entry.get("applied") and entry.get("verified"):
                session.add(
                    AuditEvent(
                        packet_id=packet_id,
                        document_id=document_id,
                        event_type=AuditEventType.REDACTION_APPLIED,
                        user_id=candidate.approval.approver if candidate.approval else "system",
                        event_metadata={
                            "candidate_id": str(candidate.id),
                            "job_id": entry.get("job_id"),
                        },
                    )
                )
                session.add(
                    AuditEvent(
                        packet_id=packet_id,
                        document_id=document_id,
                        event_type=AuditEventType.REDACTION_VERIFIED,
                        user_id=candidate.approval.approver if candidate.approval else "system",
                        event_metadata={
                            "candidate_id": str(candidate.id),
                            "text_still_present": entry.get("text_still_present", False),
                        },
                    )
                )
            elif entry.get("applied") is False:
                candidate.status = RedactionStatus.FAILED
                failed.append(
                    {
                        "candidate_id": str(candidate.id),
                        "error": entry.get("error", "unknown"),
                    }
                )

        results.append(
            {
                "document_id": str(document_id),
                "candidates_applied": len(
                    [c for c in batch if c.status == RedactionStatus.APPLIED]
                ),
                "candidates_failed": len(failed),
                "failures": failed,
                "job_id": next(
                    (e.get("job_id") for e in apply_results.values() if e.get("job_id")),
                    None,
                ),
            }
        )

    await session.commit()

    return {"results": results}


def _finalize_applied_batch(session: AsyncSession, batch: list, results: dict) -> None:
    """Mark candidates FAILED when their scrub did not complete; the
    orchestrator already set APPLIED + verification fields for successes."""
    for candidate in batch:
        entry = results.get(str(candidate.id), {})
        if entry.get("applied") is False:
            candidate.status = RedactionStatus.FAILED


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
