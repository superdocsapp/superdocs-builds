import shutil
import uuid
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
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


UPLOAD_DIR = (
    Path(__file__).resolve().parents[2]
    / "uploads"
)


ALLOWED_EXTENSIONS = {
    ".docx",
}


class FindingDecisionRequest(BaseModel):
    decision: str


def validate_docx_file(
    file: UploadFile,
    field_name: str,
) -> None:
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} is required.",
        )

    extension = Path(
        file.filename
    ).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field_name} must be a DOCX file."
            ),
        )


async def save_upload(
    file: UploadFile,
    destination: Path,
) -> None:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with destination.open("wb") as output:
        shutil.copyfileobj(
            file.file,
            output,
        )


@router.post("/analyze")
async def analyze_redline(
    dealer_file: UploadFile = File(...),
    master_file: UploadFile = File(...),
    playbook_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze uploaded dealer, master, and playbook
    documents.

    The dealer agreement is also loaded into a
    SuperDocs session so that the same session can
    later be used for applying approved redlines
    and exporting the updated document.
    """

    # --------------------------------------------------
    # Validate uploaded files
    # --------------------------------------------------

    validate_docx_file(
        dealer_file,
        "dealer_file",
    )

    validate_docx_file(
        master_file,
        "master_file",
    )

    validate_docx_file(
        playbook_file,
        "playbook_file",
    )

    # --------------------------------------------------
    # Create temporary upload directory
    # --------------------------------------------------

    request_id = uuid.uuid4()

    request_upload_dir = (
        UPLOAD_DIR / str(request_id)
    )

    dealer_path = (
        request_upload_dir
        / "dealer-agreement.docx"
    )

    master_path = (
        request_upload_dir
        / "master-agreement.docx"
    )

    playbook_path = (
        request_upload_dir
        / "negotiation-playbook.docx"
    )

    try:
        # --------------------------------------------------
        # Save uploaded documents temporarily
        # --------------------------------------------------

        await save_upload(
            dealer_file,
            dealer_path,
        )

        await save_upload(
            master_file,
            master_path,
        )

        await save_upload(
            playbook_file,
            playbook_path,
        )

        # --------------------------------------------------
        # Analyze documents locally
        # --------------------------------------------------

        analysis = analyze_agreements(
            master_path=master_path,
            dealer_path=dealer_path,
            playbook_path=playbook_path,
        )

        # --------------------------------------------------
        # Create one SuperDocs session for this review
        # --------------------------------------------------

        session_id = str(uuid.uuid4())

        client = SuperDocsClient()

        # --------------------------------------------------
        # Load dealer agreement into SuperDocs
        #
        # This is important because the same session is
        # later used by apply and export.
        # --------------------------------------------------

        try:
            dealer_document = (
                await client.upload_document(
                    file_path=dealer_path,
                    session_id=session_id,
                )
            )

        except SuperDocsError as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "SuperDocs document upload failed: "
                    f"{exc}"
                ),
            )

        # --------------------------------------------------
        # Create database review
        # --------------------------------------------------

        review = await create_redline_review(
            db=db,
            session_id=session_id,
            analysis=analysis,
        )

        # --------------------------------------------------
        # Return analysis + SuperDocs document information
        # --------------------------------------------------

        return {
            "review_id": str(review.id),
            "session_id": session_id,
            "dealer_document": dealer_document,
            **analysis,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    finally:
        # --------------------------------------------------
        # Delete temporary uploaded files
        # --------------------------------------------------

        shutil.rmtree(
            request_upload_dir,
            ignore_errors=True,
        )


@router.get("/reviews/{review_id}")
async def get_redline_review(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
):
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
    review_id: UUID,
    finding_id: UUID,
    payload: FindingDecisionRequest,
    db: AsyncSession = Depends(get_db),
):
    # --------------------------------------------------
    # Validate decision
    # --------------------------------------------------

    if payload.decision not in {
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
    # Verify review exists
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
    # Find finding
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
    # Prevent duplicate decisions
    # --------------------------------------------------

    if finding.decision != "pending":
        raise HTTPException(
            status_code=409,
            detail=(
                "This finding has already been "
                "reviewed."
            ),
        )

    finding.decision = payload.decision

    # --------------------------------------------------
    # Check remaining pending findings
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
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    # --------------------------------------------------
    # Get review
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
    # Prevent duplicate apply
    # --------------------------------------------------

    if review.status == "applied":
        raise HTTPException(
            status_code=409,
            detail=(
                "This review has already been applied."
            ),
        )

    # --------------------------------------------------
    # Make sure all findings were reviewed
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
    # Load findings
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
    # Apply approved redlines in SuperDocs
    # --------------------------------------------------

    client = SuperDocsClient()

    try:
        result = await apply_approved_redlines(
            client=client,
            session_id=review.session_id,
            findings=finding_data,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"SuperDocs error: {exc}",
        )

    # --------------------------------------------------
    # Mark review as applied
    # --------------------------------------------------

    review.status = "applied"

    await db.commit()

    return {
        "review_id": str(review_id),
        "status": review.status,
        **result,
    }


@router.post(
    "/reviews/{review_id}/export"
)
async def export_review(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    # --------------------------------------------------
    # Get review
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
    # Export only after apply
    # --------------------------------------------------

    if review.status != "applied":
        raise HTTPException(
            status_code=409,
            detail=(
                "The review must be applied "
                "before it can be exported."
            ),
        )

    # --------------------------------------------------
    # Export updated document from SuperDocs
    #
    # The review.session_id is the same session used
    # during /analyze to load the dealer document.
    # --------------------------------------------------

    client = SuperDocsClient()

    filename = (
        "dealer-agreement-redlined.docx"
    )

    try:
        document_bytes = (
            await client.export_document(
                session_id=review.session_id,
                filename=filename,
            )
        )

    except SuperDocsError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"SuperDocs export failed: {exc}"
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"SuperDocs export failed: {exc}"
            ),
        )

    # --------------------------------------------------
    # Return DOCX
    # --------------------------------------------------

    return Response(
        content=document_bytes,
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