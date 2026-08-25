"""
Baseline Contradiction Check.

Detects contradictions between new claims and approved baseline claims.
"""

import json
from typing import List, Optional, Dict, Any
from uuid import UUID

from backend.core.quality_gate.checks import BaseCheck, CheckResult, CheckStatus, CheckSeverity
from backend.repositories.review import ClaimRepository
from backend.repositories.document import DocumentChunkRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class BaselineContradictionCheck(BaseCheck):
    """
    Check for contradictions against approved baseline claims.

    Uses semantic similarity to find related claims,
    then compares values to detect contradictions.

    Critical behavior: NO silent resolution. All contradictions
    must be surfaced to human reviewer.
    """

    name = "baseline_contradiction"
    severity = CheckSeverity.ERROR
    blocking = True  # Contradictions MUST block

    def __init__(
        self,
        claim_repo: ClaimRepository,
        chunk_repo: DocumentChunkRepository,
        lineage_repo=None,
        memo_section_repo=None,
        similarity_threshold: float = 0.7
    ):
        """
        Initialize baseline contradiction check.

        Args:
            claim_repo: Claim repository
            chunk_repo: Chunk repository for semantic search
            lineage_repo: Optional lineage repository for creating contradiction links
            memo_section_repo: Optional memo section repository for post-generation checks
            similarity_threshold: Similarity threshold for related claims
        """
        self.claim_repo = claim_repo
        self.chunk_repo = chunk_repo
        self.lineage_repo = lineage_repo
        self.memo_section_repo = memo_section_repo
        self.similarity_threshold = similarity_threshold

    async def run(self, state: Dict[str, Any], config: Dict[str, Any]) -> CheckResult:
        """
        Check for contradictions against baseline claims.

        Args:
            state: Workflow state with:
                - extracted_claims: List of new claims (Claim objects)
                - baseline_run_id: ID of baseline run
                - workflow_run_id: Current run ID

        Returns:
            CheckResult with contradiction details

        Process:
        1. Load approved claims from baseline
        2. For each new claim:
           - Find semantically similar baseline claims
           - Compare values (HS codes, duty rates, etc.)
           - If contradiction detected → add to findings
        3. NO silent resolution - all contradictions surfaced
        """
        # Support both dict and Pydantic model state
        baseline_run_id = state.get("baseline_run_id") if isinstance(state, dict) else getattr(state, "baseline_run_id", None)

        if not baseline_run_id:
            return self.skip("No baseline run ID - no previous classification exists for comparison.")

        # Get extracted claims from state (legacy) or memo section recommendations (Phase 8)
        extracted_claims = state.get("extracted_claims", []) if isinstance(state, dict) else getattr(state, "extracted_claims", [])
        memo_recommendation_hs = await self._get_memo_recommendation_hs(state)

        if not extracted_claims and not memo_recommendation_hs:
            return self.skip("No new claims or memo recommendation to check")

        logger.info(
            "checking_baseline_contradictions",
            new_claims_count=len(extracted_claims),
            baseline_run_id=baseline_run_id
        )

        # Load approved baseline claims
        baseline_claims = await self._load_baseline_claims(UUID(baseline_run_id))

        if not baseline_claims:
            logger.warning("no_baseline_claims", run_id=baseline_run_id)
            return self.passed("No baseline claims to compare against")

        # Check each new claim for contradictions
        contradictions = []

        for new_claim in extracted_claims:
            claim_contradictions = await self._check_claim_contradictions(
                new_claim=new_claim,
                baseline_claims=baseline_claims
            )

            contradictions.extend(claim_contradictions)

        if memo_recommendation_hs:
            baseline_rec_hs = await self._get_baseline_recommendation_hs(UUID(baseline_run_id))
            if baseline_rec_hs and baseline_rec_hs != memo_recommendation_hs:
                contradictions.append({
                    "type": "hs_code_mismatch",
                    "baseline_value": baseline_rec_hs,
                    "new_value": memo_recommendation_hs,
                    "message": (
                        f"Recommended HS code {memo_recommendation_hs} contradicts "
                        f"baseline {baseline_rec_hs}"
                    ),
                })

        # Return result
        if contradictions:
            # Create lineage links for contradictions if lineage repo available
            if self.lineage_repo:
                await self._create_contradiction_lineage(
                    contradictions=contradictions,
                    baseline_run_id=UUID(baseline_run_id),
                    workflow_run_id=UUID(state.get("workflow_run_id") if isinstance(state, dict) else state.workflow_run_id)
                )

            details = {
                "contradictions": contradictions,
                "total_contradictions": len(contradictions),
                "baseline_run_id": baseline_run_id
            }

            message = (
                f"Found {len(contradictions)} contradiction(s) against baseline. "
                f"Human review required. Baseline MUST NOT be automatically overwritten."
            )

            logger.error(
                "baseline_contradictions_found",
                count=len(contradictions),
                baseline_run_id=baseline_run_id
            )

            return self.failed(message, details)

        logger.info(
            "baseline_contradiction_check_complete",
            contradictions=0,
            baseline_run_id=baseline_run_id
        )

        return self.passed(f"No contradictions against baseline run {baseline_run_id}")

    async def _get_memo_recommendation_hs(self, state: Dict[str, Any]) -> Optional[str]:
        workflow_run_id = state.get("workflow_run_id") if isinstance(state, dict) else getattr(state, "workflow_run_id", None)
        if not self.memo_section_repo or not workflow_run_id:
            return None
        section = await self.memo_section_repo.get_by_run_and_type(
            UUID(workflow_run_id),
            "recommended_classification",
        )
        if not section or not section.structured_data:
            return None
        recommendation = section.structured_data.get("recommendation", {})
        return recommendation.get("hs_code")

    async def _get_baseline_recommendation_hs(self, baseline_run_id: UUID) -> Optional[str]:
        if not self.memo_section_repo:
            return None
        section = await self.memo_section_repo.get_by_run_and_type(
            baseline_run_id,
            "recommended_classification",
        )
        if not section or not section.structured_data:
            return None
        recommendation = section.structured_data.get("recommendation", {})
        return recommendation.get("hs_code")

    async def _load_baseline_claims(
        self,
        baseline_run_id: UUID
    ) -> List[Any]:
        """Load approved claims from baseline run."""
        logger.info("loading_baseline_claims", run_id=str(baseline_run_id))

        claims = await self.claim_repo.get_approved_claims_for_run(baseline_run_id)
        return claims

    async def _check_claim_contradictions(
        self,
        new_claim: Any,
        baseline_claims: List[Any]
    ) -> List[Dict[str, Any]]:
        """
        Check if new claim contradicts any baseline claims.

        Args:
            new_claim: New claim to check (can be Pydantic model or DB model)
            baseline_claims: List of approved baseline claims

        Returns:
            List of contradiction details
        """
        contradictions = []

        # Parse new claim content
        new_content = self._parse_claim_content(new_claim)

        if not new_content:
            return contradictions

        # Find semantically similar baseline claims
        similar_claims = await self._find_similar_claims(
            new_claim=new_claim,
            baseline_claims=baseline_claims
        )

        # Check each similar claim for contradictions
        for baseline_claim in similar_claims:
            baseline_content = self._parse_claim_content(baseline_claim)

            if not baseline_content:
                continue

            # Detect contradictions
            contradiction = self._detect_contradiction(
                new_content=new_content,
                baseline_content=baseline_content
            )

            if contradiction:
                contradiction_detail = {
                    "new_claim_id": str(getattr(new_claim, 'id', 'unknown')),
                    "new_claim_type": getattr(new_claim, 'claim_type', 'unknown'),
                    "baseline_claim_id": str(baseline_claim.id),
                    "baseline_claim_type": baseline_claim.claim_type,
                    "field": contradiction["field"],
                    "baseline_value": contradiction["baseline_value"],
                    "new_value": contradiction["new_value"],
                    "description_similarity": contradiction.get("similarity", 1.0)
                }

                contradictions.append(contradiction_detail)

                logger.warning(
                    "contradiction_detected",
                    new_claim=getattr(new_claim, 'id', 'unknown'),
                    baseline_claim_id=str(baseline_claim.id),
                    field=contradiction["field"]
                )

        return contradictions

    async def _find_similar_claims(
        self,
        new_claim: Any,
        baseline_claims: List[Any]
    ) -> List[Any]:
        """
        Find semantically similar baseline claims.

        Args:
            new_claim: New claim (can be TariffClaim Pydantic model or DB Claim)
            baseline_claims: Baseline claims pool (DB Claim models)

        Returns:
            List of similar baseline claims

        For Tariff workflow:
        - TariffClaim models don't have claim_type
        - They have hs_code, duty_rate fields
        - Match baseline claims that have similar descriptions
        """
        new_content = self._parse_claim_content(new_claim)
        if not new_content:
            return []

        similar = []
        for baseline_claim in baseline_claims:
            baseline_content = self._parse_claim_content(baseline_claim)
            if not baseline_content:
                continue

            # Check if they reference similar products/content
            if self._are_descriptions_similar(new_content, baseline_content):
                similar.append(baseline_claim)

        return similar

    def _parse_claim_content(self, claim: Any) -> Optional[Dict[str, Any]]:
        """Parse claim content JSON."""
        # Check for content field first (DB models and Mocks)
        if hasattr(claim, 'content'):
            # DB model or Mock with content field
            content = claim.content
            try:
                if isinstance(content, str):
                    return json.loads(content)
                elif isinstance(content, dict):
                    return content
                else:
                    return None
            except (json.JSONDecodeError, AttributeError, TypeError) as exc:
                logger.error(
                    "failed_to_parse_claim_content",
                    error=str(exc)
                )
                return None
        # Handle Pydantic models (from extracted_claims in state)
        elif hasattr(claim, 'model_dump') and callable(claim.model_dump):
            # TariffClaim Pydantic model - check it's not a Mock
            try:
                result = claim.model_dump()
                # Pydantic's model_dump returns a dict, Mock returns Mock
                if isinstance(result, dict):
                    return result
                else:
                    return None
            except Exception:
                return None
        elif hasattr(claim, '__dict__') and not hasattr(claim, 'content'):
            # Dict-like object without content field
            return dict(claim.__dict__) if hasattr(claim, '__dict__') else None
        else:
            return None

    def _detect_contradiction(
        self,
        new_content: Dict[str, Any],
        baseline_content: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Detect contradictions between new and baseline content.

        Args:
            new_content: New claim content
            baseline_content: Baseline claim content

        Returns:
            Contradiction details if found, None otherwise

        Contradiction logic:
        - Same context (similar product description)
        - Different values (different HS code or duty rate)
        """
        # Check for HS code contradictions
        if "hs_code" in new_content and "hs_code" in baseline_content:
            new_hs = str(new_content["hs_code"]).strip()
            baseline_hs = str(baseline_content["hs_code"]).strip()

            # If HS codes differ and descriptions are similar
            if new_hs != baseline_hs:
                # Check if descriptions are similar enough
                if self._are_descriptions_similar(new_content, baseline_content):
                    return {
                        "field": "hs_code",
                        "baseline_value": baseline_hs,
                        "new_value": new_hs,
                        "similarity": self._calculate_description_similarity(new_content, baseline_content)
                    }

        # Check for duty rate contradictions
        if "duty_rate" in new_content and "duty_rate" in baseline_content:
            new_rate = str(new_content["duty_rate"]).strip()
            baseline_rate = str(baseline_content["duty_rate"]).strip()

            if new_rate != baseline_rate:
                if self._are_descriptions_similar(new_content, baseline_content):
                    return {
                        "field": "duty_rate",
                        "baseline_value": baseline_rate,
                        "new_value": new_rate,
                        "similarity": self._calculate_description_similarity(new_content, baseline_content)
                    }

        # No contradiction
        return None

    def _are_descriptions_similar(
        self,
        content1: Dict[str, Any],
        content2: Dict[str, Any],
        threshold: float = 0.6
    ) -> bool:
        """
        Check if descriptions are similar enough to be the same product.

        Args:
            content1: First claim content
            content2: Second claim content
            threshold: Similarity threshold (default 0.6 for more lenient matching)

        Returns:
            True if descriptions are similar, False otherwise
        """
        similarity = self._calculate_description_similarity(content1, content2)
        return similarity >= threshold

    def _calculate_description_similarity(
        self,
        content1: Dict[str, Any],
        content2: Dict[str, Any]
    ) -> float:
        """Calculate Jaccard similarity between descriptions."""
        desc1 = content1.get("description", "").lower().strip()
        desc2 = content2.get("description", "").lower().strip()

        if not desc1 or not desc2:
            return 0.0

        # Tokenize and clean
        words1 = set(w.strip() for w in desc1.split() if len(w.strip()) > 2)
        words2 = set(w.strip() for w in desc2.split() if len(w.strip()) > 2)

        if not words1 or not words2:
            return 0.0

        # Calculate Jaccard similarity
        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union) if union else 0.0

    async def _create_contradiction_lineage(
        self,
        contradictions: List[Dict[str, Any]],
        baseline_run_id: UUID,
        workflow_run_id: UUID
    ) -> None:
        """
        Create lineage links capturing contradiction audit trail.

        Links capture:
        - baseline claim
        - incoming claim
        - conflicting field and values
        - workflow context

        Args:
            contradictions: List of contradiction details
            baseline_run_id: Baseline workflow run ID
            workflow_run_id: Current workflow run ID
        """
        if not self.lineage_repo:
            return

        for contradiction in contradictions:
            try:
                baseline_claim_id = contradiction.get("baseline_claim_id")
                new_claim_id = contradiction.get("new_claim_id")

                if not baseline_claim_id or new_claim_id == "unknown":
                    continue

                # Create lineage link documenting the contradiction
                # Note: We use a special link_type to mark contradictions
                await self.lineage_repo.create_link(
                    source_type="claim",
                    source_id=UUID(new_claim_id) if new_claim_id != "unknown" else baseline_claim_id,
                    target_type="claim",
                    target_id=UUID(baseline_claim_id),
                    link_type="contradicts",
                    workflow_run_id=workflow_run_id,
                    stage_name="quality_gate",
                    metadata={
                        "baseline_run_id": str(baseline_run_id),
                        "field": contradiction.get("field"),
                        "baseline_value": contradiction.get("baseline_value"),
                        "new_value": contradiction.get("new_value"),
                        "similarity": contradiction.get("description_similarity"),
                        "contradiction_detected": True
                    }
                )

                logger.info(
                    "contradiction_lineage_created",
                    baseline_claim_id=baseline_claim_id,
                    new_claim_id=new_claim_id,
                    field=contradiction.get("field")
                )

            except Exception as exc:
                logger.error(
                    "failed_to_create_contradiction_lineage",
                    error=str(exc),
                    contradiction=contradiction
                )
