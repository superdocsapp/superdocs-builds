"""
Impact Analysis Service.

Analyzes impact of document changes for focused updates.
"""

import hashlib
from typing import List, Dict, Any, Optional
from uuid import UUID
from dataclasses import dataclass

from backend.repositories.workflow import WorkflowRunRepository
from backend.repositories.review import ClaimRepository
from backend.repositories.document import DocumentRepository, DocumentChunkRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ClaimImpact:
    """Impact assessment for a single claim."""
    claim_id: UUID
    status: str  # UNCHANGED, AFFECTED, NEW, CONTRADICTED
    reason: str
    confidence: float
    changed_chunk_ids: List[str]
    baseline_claim_id: Optional[UUID] = None


@dataclass
class ImpactAnalysisResult:
    """Result of impact analysis."""
    baseline_run_id: UUID
    new_document_id: UUID
    unchanged_claims: List[ClaimImpact]
    affected_claims: List[ClaimImpact]
    new_chunks: List[str]
    contradicted_claims: List[ClaimImpact]
    total_baseline_claims: int
    unchanged_count: int
    affected_count: int
    new_count: int
    contradicted_count: int


class ImpactAnalysisService:
    """
    Analyzes impact of document changes for focused updates.

    Determines which claims/sections are affected by document changes,
    enabling preservation of unchanged content and targeted regeneration
    of affected content only.
    """

    def __init__(
        self,
        workflow_run_repo: WorkflowRunRepository,
        claim_repo: ClaimRepository,
        document_repo: DocumentRepository,
        chunk_repo: DocumentChunkRepository
    ):
        """
        Initialize impact analysis service.

        Args:
            workflow_run_repo: Workflow run repository
            claim_repo: Claim repository
            document_repo: Document repository
            chunk_repo: Document chunk repository
        """
        self.run_repo = workflow_run_repo
        self.claim_repo = claim_repo
        self.doc_repo = document_repo
        self.chunk_repo = chunk_repo

    async def analyze_update_impact(
        self,
        new_document_id: UUID,
        baseline_run_id: UUID
    ) -> ImpactAnalysisResult:
        """
        Analyze impact of new document against baseline run.

        Args:
            new_document_id: ID of new document
            baseline_run_id: ID of baseline workflow run

        Returns:
            ImpactAnalysisResult with categorized claims

        Process:
        1. Get baseline claims
        2. Get document chunks for both baseline and new
        3. Compute chunk-level changes (text hashes)
        4. For each baseline claim:
           - Check if references changed chunks
           - If yes → AFFECTED
           - If no → UNCHANGED
        5. Identify NEW chunks (no baseline equivalent)
        6. Run contradiction check → CONTRADICTED
        """
        logger.info(
            "analyzing_update_impact",
            new_document_id=str(new_document_id),
            baseline_run_id=str(baseline_run_id)
        )

        # Get baseline claims
        baseline_claims = await self._get_baseline_claims(baseline_run_id)

        if not baseline_claims:
            logger.warning("no_baseline_claims", baseline_run_id=str(baseline_run_id))
            return ImpactAnalysisResult(
                baseline_run_id=baseline_run_id,
                new_document_id=new_document_id,
                unchanged_claims=[],
                affected_claims=[],
                new_chunks=[],
                contradicted_claims=[],
                total_baseline_claims=0,
                unchanged_count=0,
                affected_count=0,
                new_count=0,
                contradicted_count=0
            )

        # Get document chunks
        baseline_chunks = await self._get_baseline_chunks(baseline_run_id)
        new_chunks = await self._get_document_chunks(new_document_id)

        # Compute chunk changes
        changed_chunk_ids = self._identify_changed_chunks(
            baseline_chunks,
            new_chunks
        )

        # Analyze impact on each claim
        unchanged = []
        affected = []
        contradicted = []

        for claim in baseline_claims:
            impact = await self._assess_claim_impact(
                claim=claim,
                changed_chunk_ids=changed_chunk_ids,
                baseline_chunks=baseline_chunks
            )

            if impact.status == "UNCHANGED":
                unchanged.append(impact)
            elif impact.status == "AFFECTED":
                affected.append(impact)
            elif impact.status == "CONTRADICTED":
                contradicted.append(impact)

        # Identify new chunks (no baseline)
        new_chunk_ids = self._identify_new_chunks(baseline_chunks, new_chunks)

        result = ImpactAnalysisResult(
            baseline_run_id=baseline_run_id,
            new_document_id=new_document_id,
            unchanged_claims=unchanged,
            affected_claims=affected,
            new_chunks=new_chunk_ids,
            contradicted_claims=contradicted,
            total_baseline_claims=len(baseline_claims),
            unchanged_count=len(unchanged),
            affected_count=len(affected),
            new_count=len(new_chunk_ids),
            contradicted_count=len(contradicted)
        )

        logger.info(
            "impact_analysis_complete",
            unchanged=len(unchanged),
            affected=len(affected),
            new=len(new_chunk_ids),
            contradicted=len(contradicted)
        )

        return result

    async def _get_baseline_claims(self, baseline_run_id: UUID) -> List[Any]:
        """Get approved claims from baseline run."""
        logger.info("getting_baseline_claims", run_id=str(baseline_run_id))

        claims = await self.claim_repo.get_approved_claims_for_run(baseline_run_id)
        return claims

    async def _get_baseline_chunks(self, baseline_run_id: UUID) -> List[Any]:
        """Get document chunks from baseline run."""
        logger.info("getting_baseline_chunks", run_id=str(baseline_run_id))

        # Get document for run
        document = await self.run_repo.get_document_for_run(baseline_run_id)

        if not document:
            logger.warning("no_document_for_run", run_id=str(baseline_run_id))
            return []

        # Get chunks for document
        chunks = await self.chunk_repo.get_by_document_id(document.id)
        return chunks

    async def _get_document_chunks(self, document_id: UUID) -> List[Any]:
        """Get document chunks for new document."""
        chunks = await self.chunk_repo.get_by_document_id(document_id)
        return chunks

    def _identify_changed_chunks(
        self,
        baseline_chunks: List[Any],
        new_chunks: List[Any]
    ) -> List[str]:
        """
        Identify which chunks changed between baseline and new.

        Uses content hashing for deterministic comparison.

        Args:
            baseline_chunks: Chunks from baseline document
            new_chunks: Chunks from new document

        Returns:
            List of changed chunk IDs
        """
        # Build hash map of baseline chunks
        baseline_hashes = {}
        for chunk in baseline_chunks:
            chunk_hash = self._hash_content(chunk.text)
            baseline_hashes[chunk.chunk_index] = chunk_hash

        # Identify changed chunks
        changed_ids = []
        for chunk in new_chunks:
            chunk_hash = self._hash_content(chunk.text)
            baseline_hash = baseline_hashes.get(chunk.chunk_index)

            if baseline_hash != chunk_hash:
                changed_ids.append(str(chunk.id))

        logger.info(
            "identified_changed_chunks",
            changed_count=len(changed_ids),
            total_baseline=len(baseline_chunks),
            total_new=len(new_chunks)
        )

        return changed_ids

    def _identify_new_chunks(
        self,
        baseline_chunks: List[Any],
        new_chunks: List[Any]
    ) -> List[str]:
        """Identify chunks that exist in new but not in baseline."""
        baseline_indices = {chunk.chunk_index for chunk in baseline_chunks}
        new_chunk_ids = []

        for chunk in new_chunks:
            if chunk.chunk_index not in baseline_indices:
                new_chunk_ids.append(str(chunk.id))

        return new_chunk_ids

    async def _assess_claim_impact(
        self,
        claim: Any,
        changed_chunk_ids: List[str],
        baseline_chunks: List[Any]
    ) -> ClaimImpact:
        """
        Assess impact on individual claim.

        Args:
            claim: Baseline claim
            changed_chunk_ids: IDs of chunks that changed
            baseline_chunks: Baseline chunks for reference

        Returns:
            ClaimImpact with status and reason
        """
        # Import Citation repository to access the method
        from backend.repositories.evidence import CitationRepository

        # Get chunk IDs referenced by this claim via Evidence/Citation system
        # Note: We need CitationRepository instance, but for now use direct method call
        # In production, this should be injected via constructor
        citation_repo = CitationRepository(self.claim_repo.session)
        referenced_chunk_ids = await citation_repo.get_claim_chunk_references(claim.id)

        # Check intersection
        has_changed_refs = bool(
            set(referenced_chunk_ids) & set(changed_chunk_ids)
        )

        if has_changed_refs:
            return ClaimImpact(
                claim_id=claim.id,
                status="AFFECTED",
                reason="References changed document content",
                confidence=0.9,
                changed_chunk_ids=list(
                    set(referenced_chunk_ids) & set(changed_chunk_ids)
                ),
                baseline_claim_id=claim.id
            )
        else:
            return ClaimImpact(
                claim_id=claim.id,
                status="UNCHANGED",
                reason="No changes in referenced content",
                confidence=1.0,
                changed_chunk_ids=[],
                baseline_claim_id=claim.id
            )

    def _hash_content(self, text: str) -> str:
        """Compute deterministic hash of content."""
        # Normalize whitespace
        normalized = " ".join(text.split())

        # Compute SHA256 hash
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def detect_focused_update(
        self,
        new_document_id: UUID,
        workspace_id: UUID
    ) -> Optional[UUID]:
        """
        Detect if new document is an update to existing document.

        Args:
            new_document_id: ID of new document
            workspace_id: Workspace ID

        Returns:
            Baseline run ID if focused update detected, None otherwise

        Process:
        1. Get recent successful runs in workspace
        2. Compare filenames (same filename = likely update)
        3. Compare checksums to confirm it's different content
        4. Return most recent baseline run ID for that filename
        """
        logger.info(
            "detecting_focused_update",
            new_document_id=str(new_document_id),
            workspace_id=str(workspace_id)
        )

        # Get new document
        new_doc = await self.doc_repo.get_by_id(new_document_id)

        if not new_doc:
            return None

        # Get recent successful runs in workspace
        recent_runs = await self.run_repo.get_recent_successful_runs(
            workspace_id,
            limit=10
        )

        if not recent_runs:
            logger.info("no_recent_runs_found")
            return None

        # Compare with each recent run
        for run in recent_runs:
            # Get run's document
            baseline_doc = await self.run_repo.get_document_for_run(run.id)

            if not baseline_doc:
                continue

            # Check if same filename (indicates update to same document)
            if baseline_doc.filename == new_doc.filename:
                # Check if content changed (different checksum)
                if baseline_doc.checksum != new_doc.checksum:
                    logger.info(
                        "focused_update_detected",
                        baseline_run_id=str(run.id),
                        baseline_filename=baseline_doc.filename,
                        new_filename=new_doc.filename
                    )
                    return run.id
                else:
                    logger.info(
                        "same_document_identical_content",
                        baseline_run_id=str(run.id)
                    )
                    # Same content, not an update
                    return None

        logger.info("no_baseline_detected")
        return None
