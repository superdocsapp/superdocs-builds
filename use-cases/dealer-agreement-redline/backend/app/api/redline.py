import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.redline_review import (
    RedlineFinding,
    RedlineReview,
)
from app.services.redline_service import (
    analyze_agreements,
    create_redline_review,
)
from app.services.superdocs_redline import (
    apply_approved_redlines,
)
from app.superdocs.client import (
    SuperDocsClient,
    SuperDocsError,
)


router = APIRouter(
    prefix="/redline",
    tags=["redline"],
)


TEST_DATA = (
    Path(__file__).resolve().parents[3]
    / "test-data"
)


class FindingDecisionRequest(BaseModel):
    decision: str


@router.post("/analyze")
async def analyze_redline(
    db: AsyncSession = Depends(get_db),
):
    """
    Run the complete dealer agreement redline analysis.

    Flow:
        1. Create a SuperDocs session.
        2. Upload dealer agreement as active document.
        3. Upload master agreement as reference attachment.
        4. Upload negotiation playbook as reference attachment.
        5. Analyze the agreements locally.
        6. Persist the review and findings.
        7. Return the review and SuperDocs session IDs.
    """

    master_file = (
        TEST_DATA / "master-agreement.docx"
    )

    dealer_file = (
        TEST_DATA / "dealer-agreement.docx"
    )

    playbook_file = (
        TEST_DATA / "negotiation-playbook.docx"
    )

    for file in (
        master_file,
        dealer_file,
        playbook_file,
    ):
        if not file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {file}",
            )

    client = SuperDocsClient()

    # One session is used for the entire workflow.
    session_id = str(uuid.uuid4())

    try:
        # --------------------------------------------------
        # 1. Upload dealer agreement as active document.
        # --------------------------------------------------

        dealer_document = (
            await client.upload_document(
                file_path=dealer_file,
                session_id=session_id,
            )
        )

        # --------------------------------------------------
        # 2. Upload master agreement as reference.
        # --------------------------------------------------

        master_attachment = (
            await client.upload_attachment(
                file_path=master_file,
                session_id=session_id,
            )
        )

        # --------------------------------------------------
        # 3. Upload negotiation playbook as reference.
        # --------------------------------------------------

        playbook_attachment = (
            await client.upload_attachment(
                file_path=playbook_file,
                session_id=session_id,
            )
        )

        # --------------------------------------------------
        # 4. Run local redline analysis.
        # --------------------------------------------------

        analysis = analyze_agreements(
            master_path=master_file,
            dealer_path=dealer_file,
            playbook_path=playbook_file,
        )

        # --------------------------------------------------
        # 5. Persist review.
        #
        # IMPORTANT:
        # Save the SAME SuperDocs session ID.
        # This allows /apply to operate on the document
        # that was actually uploaded above.
        # --------------------------------------------------

        review = await create_redline_review(
            db=db,
            session_id=session_id,
            analysis=analysis,
        )

        return {
            "review_id": str(review.id),
            "session_id": session_id,
            "dealer_document": dealer_document,
            "master_attachment": master_attachment,
            "playbook_attachment": playbook_attachment,
            **analysis,
        }

    except SuperDocsError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@router.get("/reviews/{review_id}")
async def get_redline_review(
    review_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Get a redline review and all of its findings.
    """

    result = await db.execute(
        select(RedlineReview).where(
            RedlineReview.id == review_id
        )
    )

    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Redline review not found",
        )

    result = await db.execute(
        select(RedlineFinding)
        .where(
            RedlineFinding.review_id == review_id
        )
        .order_by(RedlineFinding.created_at)
    )

    findings = result.scalars().all()

    return {
        "review_id": str(review.id),
        "session_id": review.session_id,
        "status": review.status,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
        "findings": [
            {
                "id": str(finding.id),
                "section": finding.section,
                "master_text": finding.master_text,
                "dealer_text": finding.dealer_text,
                "deviation_type": finding.deviation_type,
                "similarity": finding.similarity,
                "classification": finding.classification,
                "reason": finding.reason,
                "counter_position": finding.counter_position,
                "decision": finding.decision,
            }
            for finding in findings
        ],
    }


@router.post(
    "/reviews/{review_id}/findings/{finding_id}/decision"
)
async def decide_redline_finding(
    review_id: uuid.UUID,
    finding_id: uuid.UUID,
    payload: FindingDecisionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Approve or reject an individual redline finding.

    A finding can only be decided once.
    Decisions cannot be changed after the review
    has been completed or applied.
    """

    # --------------------------------------------------
    # Normalize the decision.
    # --------------------------------------------------

    decision = payload.decision.strip().lower()

    if decision not in {
        "approve",
        "reject",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "Decision must be either "
                "'approve' or 'reject'."
            ),
        )

    # --------------------------------------------------
    # Verify review exists.
    # --------------------------------------------------

    result = await db.execute(
        select(RedlineReview).where(
            RedlineReview.id == review_id
        )
    )

    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Redline review not found",
        )

    # --------------------------------------------------
    # Prevent decisions after review completion.
    # --------------------------------------------------

    if review.status in {
        "completed",
        "applied",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "This review has already been "
                "completed."
            ),
        )

    # --------------------------------------------------
    # Find the requested finding.
    # --------------------------------------------------

    result = await db.execute(
        select(RedlineFinding).where(
            RedlineFinding.id == finding_id,
            RedlineFinding.review_id == review_id,
        )
    )

    finding = result.scalar_one_or_none()

    if finding is None:
        raise HTTPException(
            status_code=404,
            detail="Redline finding not found",
        )

    # --------------------------------------------------
    # Prevent changing an already-reviewed finding.
    # --------------------------------------------------

    if finding.decision != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                "This finding has already been "
                "reviewed."
            ),
        )

    finding.decision = decision

    # --------------------------------------------------
    # Check whether findings remain.
    # --------------------------------------------------

    result = await db.execute(
        select(RedlineFinding).where(
            RedlineFinding.review_id == review_id,
            RedlineFinding.decision == "pending",
        )
    )

    remaining = result.scalars().all()

    if remaining:
        review.status = "in_review"
    else:
        review.status = "completed"

    await db.commit()
    await db.refresh(finding)

    return {
        "review_id": str(review_id),
        "finding_id": str(finding_id),
        "decision": finding.decision,
        "review_status": review.status,
        "remaining_findings": len(remaining),
    }


@router.post(
    "/reviews/{review_id}/apply"
)
async def apply_review(
    review_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Apply human-approved redlines to the active
    SuperDocs document.

    All findings must have been reviewed first.
    """

    # --------------------------------------------------
    # Get review.
    # --------------------------------------------------

    result = await db.execute(
        select(RedlineReview).where(
            RedlineReview.id == review_id
        )
    )

    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Redline review not found",
        )

    # --------------------------------------------------
    # Prevent applying the same review twice.
    # --------------------------------------------------

    if review.status == "applied":
        raise HTTPException(
            status_code=409,
            detail="This review has already been applied.",
        )

    # --------------------------------------------------
    # Make sure every finding has a decision.
    # --------------------------------------------------

    result = await db.execute(
        select(RedlineFinding).where(
            RedlineFinding.review_id == review_id,
            RedlineFinding.decision == "pending",
        )
    )

    pending = result.scalars().all()

    if pending:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(pending)} finding(s) "
                "still require review."
            ),
        )

    # --------------------------------------------------
    # Load all findings.
    # --------------------------------------------------

    result = await db.execute(
        select(RedlineFinding)
        .where(
            RedlineFinding.review_id == review_id
        )
        .order_by(RedlineFinding.created_at)
    )

    findings = result.scalars().all()

    finding_data = [
        {
            "id": str(finding.id),
            "section": finding.section,
            "dealer_text": finding.dealer_text,
            "counter_position": finding.counter_position,
            "decision": finding.decision,
            "classification": finding.classification,
        }
        for finding in findings
    ]

    # --------------------------------------------------
    # Apply approved findings to SuperDocs.
    #
    # apply_approved_redlines() filters out findings
    # whose decision is not "approve".
    # --------------------------------------------------

    client = SuperDocsClient()

    try:
        result = await apply_approved_redlines(
            client=client,
            session_id=review.session_id,
            findings=finding_data,
        )

    except SuperDocsError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"SuperDocs error: {exc}",
        )

    review.status = "applied"

    await db.commit()

    return {
        "review_id": str(review_id),
        "session_id": review.session_id,
        "status": review.status,
        **result,
    }


@router.get(
    "/reviews/{review_id}/export"
)
async def export_review(
    review_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Export the applied dealer agreement as DOCX.
    """

    result = await db.execute(
        select(RedlineReview).where(
            RedlineReview.id == review_id
        )
    )

    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Redline review not found",
        )

    # --------------------------------------------------
    # Export is only allowed after apply.
    # --------------------------------------------------

    if review.status != "applied":
        raise HTTPException(
            status_code=409,
            detail=(
                "The review must be applied "
                "before exporting."
            ),
        )

    client = SuperDocsClient()

    filename = "dealer-agreement-redlined.docx"

    try:
        document = await client.export_document(
            session_id=review.session_id,
            filename=filename,
        )

    except SuperDocsError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        )

    return Response(
        content=document,
        media_type=(
            "application/vnd.openxmlformats-"
            "officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            ),
        },
    )