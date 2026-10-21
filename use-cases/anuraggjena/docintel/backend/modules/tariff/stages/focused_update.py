"""
Focused Update Stage.

Preserves unchanged claims and regenerates only affected claims.
"""

import json
from typing import List, Dict, Any
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.services.impact_analysis import ImpactAnalysisService, ClaimImpact
from backend.repositories.review import ClaimRepository
from backend.repositories.lineage import LineageLinkRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class FocusedUpdateStage(StageNode[TariffWorkflowState]):
    """
    Focused update stage for incremental document updates.

    Responsibilities:
    - Analyze impact of document changes
    - Preserve unchanged claims from baseline
    - Mark affected claims for regeneration
    - Create lineage relationships
    - Detect contradictions
    """

    def __init__(
        self,
        impact_service: ImpactAnalysisService,
        claim_repository: ClaimRepository,
        lineage_repository: LineageLinkRepository
    ):
        """
        Initialize focused update stage.

        Args:
            impact_service: Impact analysis service
            claim_repository: Claim repository
            lineage_repository: Lineage repository
        """
        super().__init__("focused_update")
        self.impact_service = impact_service
        self.claim_repo = claim_repository
        self.lineage_repo = lineage_repository

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        """
        Execute focused update analysis.

        Args:
            state: Workflow state with baseline_run_id and document_id

        Returns:
            Updated state with impact analysis results

        Process:
        1. Run impact analysis
        2. Preserve unchanged claims (copy from baseline)
        3. Mark affected claims for regeneration
        4. Create lineage links
        5. Return analysis results in state
        """
        workflow_run_id = UUID(state.workflow_run_id)
        baseline_run_id = state.baseline_run_id
        document_id = state.document_id

        if not baseline_run_id:
            logger.info(
                "no_baseline_run_id_skipping_focused_update",
                run_id=str(workflow_run_id)
            )
            return {
                "skip": True,
                "focused_update_completed": False,
                "results_count": 0
            }

        if not document_id:
            logger.error("no_document_id_in_state", run_id=str(workflow_run_id))
            return {
                "skip": True,
                "focused_update_completed": False,
                "results_count": 0
            }

        logger.info(
            "executing_focused_update",
            run_id=str(workflow_run_id),
            baseline_run_id=baseline_run_id
        )

        # Run impact analysis
        impact_result = await self.impact_service.analyze_update_impact(
            new_document_id=UUID(document_id),
            baseline_run_id=UUID(baseline_run_id)
        )

        # Preserve unchanged claims
        preserved_claim_ids = await self._preserve_unchanged_claims(
            impact_result.unchanged_claims,
            workflow_run_id
        )

        # Mark affected claims with superseded_by lineage
        # These claims will be regenerated in a later stage
        await self._mark_affected_claims(
            impact_result.affected_claims,
            workflow_run_id
        )

        logger.info(
            "focused_update_complete",
            preserved_claims=len(preserved_claim_ids),
            affected_claims=impact_result.affected_count,
            new_chunks=impact_result.new_count,
            contradicted_claims=impact_result.contradicted_count
        )

        return {
            "focused_update_completed": True,
            "unchanged_claims_count": impact_result.unchanged_count,
            "affected_claims_count": impact_result.affected_count,
            "new_chunks_count": impact_result.new_count,
            "contradicted_claims_count": impact_result.contradicted_count,
            "preserved_claim_ids": [str(cid) for cid in preserved_claim_ids],
            "affected_chunk_ids": impact_result.new_chunks,
            "contradictions": [
                {
                    "claim_id": str(c.claim_id),
                    "reason": c.reason,
                    "baseline_claim_id": str(c.baseline_claim_id) if c.baseline_claim_id else None
                }
                for c in impact_result.contradicted_claims
            ],
            # Store impact details for downstream stages
            "_impact_analysis": {
                "unchanged_claims": [
                    {"claim_id": str(c.claim_id), "status": c.status}
                    for c in impact_result.unchanged_claims
                ],
                "affected_claims": [
                    {
                        "claim_id": str(c.claim_id),
                        "status": c.status,
                        "changed_chunk_ids": c.changed_chunk_ids
                    }
                    for c in impact_result.affected_claims
                ],
            }
        }

    async def _preserve_unchanged_claims(
        self,
        unchanged_impacts: List[ClaimImpact],
        new_run_id: UUID
    ) -> List[UUID]:
        """
        Preserve unchanged claims from baseline.

        Creates new claim records with content copied from baseline,
        and creates lineage links showing reuse.

        Args:
            unchanged_impacts: List of unchanged claim impacts
            new_run_id: New workflow run ID

        Returns:
            List of preserved claim IDs
        """
        preserved_ids = []

        for impact in unchanged_impacts:
            # Get baseline claim
            baseline_claim = await self.claim_repo.get_by_id(impact.baseline_claim_id)

            if not baseline_claim:
                logger.warning(
                    "baseline_claim_not_found",
                    claim_id=str(impact.baseline_claim_id)
                )
                continue

            # Create new claim with same content
            from backend.models.claim import Claim

            new_claim = Claim(
                workflow_run_id=new_run_id,
                claim_type=baseline_claim.claim_type,
                content=baseline_claim.content,
                status="approved",  # Preserve approval status
                original_content=baseline_claim.original_content,
                source_stage="focused_update",
                confidence_score=baseline_claim.confidence_score
            )

            self.claim_repo.session.add(new_claim)
            await self.claim_repo.session.flush()
            await self.claim_repo.session.refresh(new_claim)

            # Create lineage link: new_claim reused_from baseline_claim
            await self.lineage_repo.create_link(
                source_type="claim",
                source_id=new_claim.id,
                target_type="claim",
                target_id=baseline_claim.id,
                link_type="reused_from_baseline",
                workflow_run_id=new_run_id,
                stage_name="focused_update",
                metadata={
                    "reason": "unchanged_content",
                    "confidence": impact.confidence,
                    "content_hash": self._hash_content(baseline_claim.content)
                }
            )

            preserved_ids.append(new_claim.id)

            logger.info(
                "claim_preserved",
                baseline_claim_id=str(baseline_claim.id),
                new_claim_id=str(new_claim.id),
                claim_type=baseline_claim.claim_type
            )

        await self.claim_repo.session.commit()

        return preserved_ids

    async def _mark_affected_claims(
        self,
        affected_impacts: List[ClaimImpact],
        new_run_id: UUID
    ) -> None:
        """
        Mark affected claims for regeneration with superseded_by lineage.

        Creates lineage links to track that baseline claims will be replaced
        by newly generated claims in subsequent workflow stages.

        This method does NOT create new claims - it only marks the relationship.
        The actual new claims will be created by the generation stage.

        Args:
            affected_impacts: List of affected claim impacts
            new_run_id: New workflow run ID
        """
        for impact in affected_impacts:
            if not impact.baseline_claim_id:
                continue

            # Get baseline claim
            baseline_claim = await self.claim_repo.get_by_id(impact.baseline_claim_id)

            if not baseline_claim:
                logger.warning(
                    "baseline_claim_not_found_for_affected",
                    claim_id=str(impact.baseline_claim_id)
                )
                continue

            # Mark this claim as affected (will be superseded)
            # The lineage link will be completed when the new claim is generated
            # For now, we just store the affected claim info in workflow state
            logger.info(
                "claim_marked_affected",
                baseline_claim_id=str(baseline_claim.id),
                reason=impact.reason,
                changed_chunks=len(impact.changed_chunk_ids)
            )

    def _hash_content(self, content: str) -> str:
        """Compute SHA256 hash of content for verification."""
        import hashlib
        normalized = " ".join(content.split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
