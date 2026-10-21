from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import (
    get_db,
    get_current_user,
    require_workspace_access,
    verify_review_workspace_access,
    verify_claim_workspace_access
)
from backend.models.user import User
from backend.models.workspace import Workspace
from backend.models.review import Review
from backend.models.claim import Claim
from backend.services.review import ReviewService
from backend.repositories.review import ReviewRepository, ClaimRepository
from backend.repositories.lineage import LineageLinkRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/reviews", tags=["reviews"])


# Schemas
class ReviewCreate(BaseModel):
    workflow_run_id: str
    workspace_id: str
    reviewer_id: Optional[str] = None


class ReviewUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class ReviewResponse(BaseModel):
    id: UUID
    workflow_run_id: UUID
    workspace_id: UUID
    status: str
    reviewer_id: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime, _info) -> str:
        """Serialize datetime to ISO format string"""
        return dt.isoformat()


class ClaimCreate(BaseModel):
    workflow_run_id: str
    claim_type: str
    content: str
    review_id: Optional[str] = None
    source_stage: Optional[str] = None


class ClaimUpdate(BaseModel):
    content: str
    edited_by: Optional[str] = None


class ClaimRegenerate(BaseModel):
    new_content: str
    workflow_run_id: str
    regeneration_reason: Optional[str] = "reviewer_rejection"


class ClaimResponse(BaseModel):
    id: UUID
    workflow_run_id: UUID
    review_id: Optional[UUID]
    claim_type: str
    content: str
    status: str
    original_content: Optional[str]
    edited_by: Optional[str]
    source_stage: Optional[str]
    confidence_score: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime, _info) -> str:
        """Serialize datetime to ISO format string"""
        return dt.isoformat()


async def get_review_service(db: AsyncSession = Depends(get_db)) -> ReviewService:
    """Dependency for review service"""
    review_repo = ReviewRepository(db)
    claim_repo = ClaimRepository(db)
    lineage_link_repo = LineageLinkRepository(db)
    return ReviewService(review_repo, claim_repo, lineage_link_repo)


# Review endpoints
@router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    review: ReviewCreate,
    service: ReviewService = Depends(get_review_service)
):
    """Create a new review"""
    created = await service.create_review(
        workflow_run_id=UUID(review.workflow_run_id),
        workspace_id=UUID(review.workspace_id),
        reviewer_id=review.reviewer_id
    )
    return created


@router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(
    review_id: UUID,
    review: Review = Depends(verify_review_workspace_access)
):
    """Get review by ID (requires workspace ownership)"""
    return review


@router.get("/workspace/{workspace_id}", response_model=List[ReviewResponse])
async def list_workspace_reviews(
    workspace_id: UUID,
    workspace: Workspace = Depends(require_workspace_access),
    service: ReviewService = Depends(get_review_service)
):
    """List reviews for a workspace (requires ownership)"""
    reviews = await service.list_workspace_reviews(workspace_id)
    return reviews


class BulkApproveResponse(BaseModel):
    approved_count: int
    review_id: str


@router.patch("/{review_id}", response_model=ReviewResponse)
async def update_review(
    review_id: UUID,
    update: ReviewUpdate,
    review: Review = Depends(verify_review_workspace_access),
    service: ReviewService = Depends(get_review_service)
):
    """Update review status (requires workspace ownership)"""
    updated = await service.update_review_status(
        review_id=review_id,
        status=update.status,
        notes=update.notes
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found"
        )

    return updated


@router.post("/{review_id}/approve-all", response_model=BulkApproveResponse)
async def approve_all_review_claims(
    review_id: UUID,
    review: Review = Depends(verify_review_workspace_access),
    service: ReviewService = Depends(get_review_service)
):
    """Bulk approve all pending claims for a review (requires workspace ownership)"""
    result = await service.approve_all_for_review(review_id)
    return result


# Claim endpoints
@router.post("/claims", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
async def create_claim(
    claim: ClaimCreate,
    service: ReviewService = Depends(get_review_service)
):
    """Create a new claim"""
    created = await service.create_claim(
        workflow_run_id=UUID(claim.workflow_run_id),
        claim_type=claim.claim_type,
        content=claim.content,
        review_id=UUID(claim.review_id) if claim.review_id else None,
        source_stage=claim.source_stage
    )
    return created


@router.get("/{review_id}/claims", response_model=List[ClaimResponse])
async def list_review_claims(
    review_id: UUID,
    review: Review = Depends(verify_review_workspace_access),
    service: ReviewService = Depends(get_review_service)
):
    """List claims for a review (requires workspace ownership)"""
    claims = await service.list_review_claims(review_id)
    return claims


@router.patch("/claims/{claim_id}", response_model=ClaimResponse)
async def update_claim(
    claim_id: UUID,
    update: ClaimUpdate,
    claim: Claim = Depends(verify_claim_workspace_access),
    service: ReviewService = Depends(get_review_service)
):
    """Update claim content"""
    updated = await service.update_claim(
        claim_id=claim_id,
        content=update.content,
        edited_by=update.edited_by
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim {claim_id} not found"
        )

    return updated


@router.post("/claims/{claim_id}/approve", response_model=ClaimResponse)
async def approve_claim(
    claim_id: UUID,
    claim: Claim = Depends(verify_claim_workspace_access),
    service: ReviewService = Depends(get_review_service)
):
    """Approve a claim. Requires workspace ownership (verified via claim → review → run → workspace)."""
    approved = await service.approve_claim(claim_id)

    if not approved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim {claim_id} not found"
        )

    return approved


@router.post("/claims/{claim_id}/reject", response_model=ClaimResponse)
async def reject_claim(
    claim_id: UUID,
    claim: Claim = Depends(verify_claim_workspace_access),
    service: ReviewService = Depends(get_review_service)
):
    """Reject a claim. Requires workspace ownership (verified via claim → review → run → workspace)."""
    rejected = await service.reject_claim(claim_id)

    if not rejected:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim {claim_id} not found"
        )

    return rejected


@router.post("/claims/{claim_id}/regenerate", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
async def regenerate_claim(
    claim_id: UUID,
    regenerate: ClaimRegenerate,
    claim: Claim = Depends(verify_claim_workspace_access),
    service: ReviewService = Depends(get_review_service)
):
    """Regenerate a rejected claim. Requires workspace ownership."""
    try:
        new_claim = await service.regenerate_claim(
            original_claim_id=claim_id,
            new_content=regenerate.new_content,
            workflow_run_id=UUID(regenerate.workflow_run_id),
            regeneration_reason=regenerate.regeneration_reason
        )
        return new_claim
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
