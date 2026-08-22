from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.session import get_db
from app.db.models import AssessmentModel, FindingModel, AttestationCycleModel
from app.schemas.enums import AttestationStatus, ReviewDecision
from app.schemas.assessment import AssessmentReviewRequest, AssessmentResponse
from app.services.superdocs_service import SuperDocsClientService
from app.schemas.superdocs import SuperDocsApproveRequest

router = APIRouter(prefix="/review", tags=["Review Gate"])


@router.post("/{assessment_id}/submit", response_model=AssessmentResponse)
async def submit_review(
    assessment_id: str,
    payload: AssessmentReviewRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Human-in-the-loop review gate.
    Approves/rejects findings item-by-item and commits final decision to SuperDocs and DB.
    """
    stmt = select(AssessmentModel).where(AssessmentModel.id == assessment_id)
    res = await db.execute(stmt)
    assessment = res.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")

    # Load attestation
    att_stmt = select(AttestationCycleModel).where(AttestationCycleModel.id == assessment.attestation_id)
    att_res = await db.execute(att_stmt)
    attestation = att_res.scalar_one_or_none()

    approved_diff_ids = []
    rejected_diff_ids = []

    # Update individual findings
    for decision in payload.finding_decisions:
        f_stmt = select(FindingModel).where(FindingModel.id == decision.finding_id)
        f_res = await db.execute(f_stmt)
        finding = f_res.scalar_one_or_none()
        if finding:
            finding.review_decision = decision.review_decision.value
            if decision.review_notes:
                finding.review_notes = decision.review_notes

            if decision.review_decision == ReviewDecision.ACCEPTED:
                approved_diff_ids.append(finding.id)
            else:
                rejected_diff_ids.append(finding.id)

    assessment.is_approved = payload.is_approved
    assessment.approved_by = payload.approved_by
    assessment.approved_at = datetime.now(timezone.utc)

    # If SuperDocs document exists, signal approval/rejection to SuperDocs
    if attestation and attestation.issued_document_id:
        sd_client = SuperDocsClientService()
        await sd_client.approve_changes(SuperDocsApproveRequest(
            document_id=attestation.issued_document_id,
            approved_diff_ids=approved_diff_ids,
            rejected_diff_ids=rejected_diff_ids
        ))

    # Update attestation status
    if attestation:
        if payload.is_approved:
            # Check if any accepted critical findings remain
            has_accepted_issues = any(d.review_decision == ReviewDecision.ACCEPTED for d in payload.finding_decisions)
            attestation.status = (
                AttestationStatus.FOLLOW_UP_REQUIRED.value
                if has_accepted_issues
                else AttestationStatus.APPROVED.value
            )
        else:
            attestation.status = AttestationStatus.UNDER_REVIEW.value

    await db.commit()
    await db.refresh(assessment)

    # Return refreshed assessment with findings
    refreshed_stmt = (
        select(AssessmentModel)
        .options(selectinload(AssessmentModel.findings))
        .where(AssessmentModel.id == assessment_id)
    )
    refreshed_res = await db.execute(refreshed_stmt)
    return refreshed_res.scalar_one()
