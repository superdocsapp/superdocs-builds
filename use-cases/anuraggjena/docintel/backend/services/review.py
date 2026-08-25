from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone

from backend.repositories.review import ReviewRepository, ClaimRepository
from backend.repositories.lineage import LineageLinkRepository
from backend.models.review import Review
from backend.models.claim import Claim
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ReviewService:
    """Service for managing reviews and claims"""

    def __init__(
        self,
        review_repository: ReviewRepository,
        claim_repository: ClaimRepository,
        lineage_link_repository: Optional[LineageLinkRepository] = None
    ):
        self.review_repository = review_repository
        self.claim_repository = claim_repository
        self.lineage_link_repository = lineage_link_repository

    async def create_review(
        self,
        workflow_run_id: UUID,
        workspace_id: UUID,
        reviewer_id: Optional[str] = None
    ) -> Review:
        """Create a new review for a workflow run"""
        logger.info("creating_review", workflow_run_id=str(workflow_run_id))

        review = await self.review_repository.create(
            workflow_run_id=workflow_run_id,
            workspace_id=workspace_id,
            reviewer_id=reviewer_id,
            status="in_review"
        )

        logger.info("review_created", review_id=str(review.id))
        return review

    async def get_review(self, review_id: UUID) -> Optional[Review]:
        """Get review by ID"""
        return await self.review_repository.get_by_id(review_id)

    async def list_workspace_reviews(self, workspace_id: UUID) -> List[Review]:
        """List all reviews for a workspace"""
        return await self.review_repository.list_by_workspace(workspace_id)

    async def update_review_status(
        self,
        review_id: UUID,
        status: str,
        notes: Optional[str] = None
    ) -> Optional[Review]:
        """Update review status"""
        logger.info("updating_review_status", review_id=str(review_id), status=status)

        updated = await self.review_repository.update(
            review_id,
            status=status,
            notes=notes
        )

        return updated

    async def create_claim(
        self,
        workflow_run_id: UUID,
        claim_type: str,
        content: str,
        review_id: Optional[UUID] = None,
        source_stage: Optional[str] = None
    ) -> Claim:
        """Create a new claim"""
        logger.info("creating_claim", workflow_run_id=str(workflow_run_id), claim_type=claim_type)

        claim = await self.claim_repository.create(
            workflow_run_id=workflow_run_id,
            review_id=review_id,
            claim_type=claim_type,
            content=content,
            original_content=content,  # Store original
            status="pending",
            source_stage=source_stage
        )

        return claim

    async def update_claim(
        self,
        claim_id: UUID,
        content: str,
        edited_by: Optional[str] = None
    ) -> Optional[Claim]:
        """Update claim content"""
        logger.info("updating_claim", claim_id=str(claim_id))

        updated = await self.claim_repository.update(
            claim_id,
            content=content,
            edited_by=edited_by,
            status="edited"
        )

        return updated

    async def approve_claim(self, claim_id: UUID) -> Optional[Claim]:
        """Approve a claim. Cannot reverse an already rejected claim."""
        claim = await self.claim_repository.get_by_id(claim_id)
        if not claim:
            return None
        if claim.status == "approved":
            return claim
        if claim.status == "rejected":
            logger.info("reject_claim_cannot_reverse_rejection", claim_id=str(claim_id))
            return claim

        updated = await self.claim_repository.update(claim_id, status="approved")
        
        # If all claims in the review are now resolved, update review status
        if claim.review_id:
            claims = await self.claim_repository.list_by_review(claim.review_id)
            pending = [c for c in claims if c.status == "pending"]
            if not pending:
                await self.review_repository.update(claim.review_id, status="approved")

        return updated

    async def reject_claim(self, claim_id: UUID) -> Optional[Claim]:
        """Reject a claim. Cannot reverse an already approved claim."""
        claim = await self.claim_repository.get_by_id(claim_id)
        if not claim:
            return None
        if claim.status == "rejected":
            return claim
        if claim.status == "approved":
            logger.info("approve_claim_cannot_reverse_approval", claim_id=str(claim_id))
            return claim

        updated = await self.claim_repository.update(claim_id, status="rejected")

        # If all claims in the review are now resolved, update review status
        if claim.review_id:
            claims = await self.claim_repository.list_by_review(claim.review_id)
            pending = [c for c in claims if c.status == "pending"]
            if not pending:
                await self.review_repository.update(claim.review_id, status="rejected")

        return updated

    async def approve_all_for_review(self, review_id: UUID) -> dict:
        """Bulk approve all pending claims for a review"""
        review = await self.review_repository.get_by_id(review_id)
        count = await self.claim_repository.bulk_approve_for_review(review_id)
        if review and review.workflow_run_id:
            run_count = await self.claim_repository.bulk_approve_for_run(review.workflow_run_id)
            count += run_count
        await self.review_repository.update(review_id, status="approved")
        return {
            "approved_count": count,
            "review_id": str(review_id),
        }

    async def approve_all_for_run(self, workflow_run_id: UUID) -> dict:
        """Bulk approve all pending claims for a workflow run"""
        count = await self.claim_repository.bulk_approve_for_run(workflow_run_id)
        review = await self.review_repository.get_by_workflow_run(workflow_run_id)
        if review:
            await self.review_repository.update(review.id, status="approved")
        return {
            "approved_count": count,
            "workflow_run_id": str(workflow_run_id),
        }

    async def list_review_claims(self, review_id: UUID) -> List[Claim]:
        """List all claims for a review (including associated workflow run claims)"""
        review = await self.review_repository.get_by_id(review_id)
        claims = await self.claim_repository.list_by_review(review_id)
        if review and review.workflow_run_id:
            run_claims = await self.claim_repository.list_by_workflow_run(review.workflow_run_id)
            existing_ids = {c.id for c in claims}
            for rc in run_claims:
                if rc.id not in existing_ids:
                    claims.append(rc)
        return claims

    async def _create_regeneration_link(
        self,
        new_claim_id: UUID,
        original_claim_id: UUID,
        workflow_run_id: UUID,
        regeneration_reason: str = "reviewer_rejection",
    ):
        """Create lineage link for claim regeneration.

        Args:
            new_claim_id: ID of the newly created claim
            original_claim_id: ID of the original claim being replaced
            workflow_run_id: ID of the workflow run
            regeneration_reason: Reason for regeneration (default: reviewer_rejection)
        """
        if self.lineage_link_repository:
            try:
                await self.lineage_link_repository.create_link(
                    source_type="claim",
                    source_id=new_claim_id,
                    target_type="claim",
                    target_id=original_claim_id,
                    link_type="regenerated_from",
                    workflow_run_id=workflow_run_id,
                    stage_name="review_regeneration",
                    metadata={
                        "regeneration_reason": regeneration_reason,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                logger.info(
                    "regeneration_lineage_link_created",
                    new_claim_id=str(new_claim_id),
                    original_claim_id=str(original_claim_id),
                    reason=regeneration_reason
                )
            except Exception as e:
                # Log error but don't fail the regeneration
                logger.warning(
                    "regeneration_lineage_link_failed",
                    new_claim_id=str(new_claim_id),
                    original_claim_id=str(original_claim_id),
                    error=str(e)
                )

    async def regenerate_claim(
        self,
        original_claim_id: UUID,
        new_content: str,
        workflow_run_id: UUID,
        regeneration_reason: str = "reviewer_rejection",
    ) -> Claim:
        """Create new claim to replace rejected one.

        Args:
            original_claim_id: ID of the original claim being replaced
            new_content: Content for the new claim
            workflow_run_id: ID of the workflow run
            regeneration_reason: Reason for regeneration (default: reviewer_rejection)

        Returns:
            The newly created claim
        """
        logger.info(
            "regenerating_claim",
            original_claim_id=str(original_claim_id),
            workflow_run_id=str(workflow_run_id)
        )

        # Get original claim to copy metadata
        original_claim = await self.claim_repository.get_by_id(original_claim_id)
        if not original_claim:
            raise ValueError(f"Original claim {original_claim_id} not found")

        # Create new claim
        new_claim = await self.claim_repository.create(
            workflow_run_id=workflow_run_id,
            claim_type=original_claim.claim_type,
            content=new_content,
            original_content=new_content,
            status="pending",
            source_stage=original_claim.source_stage,
        )

        # Create lineage link (optional)
        await self._create_regeneration_link(
            new_claim.id,
            original_claim_id,
            workflow_run_id,
            regeneration_reason
        )

        logger.info(
            "claim_regenerated",
            new_claim_id=str(new_claim.id),
            original_claim_id=str(original_claim_id)
        )

        return new_claim
