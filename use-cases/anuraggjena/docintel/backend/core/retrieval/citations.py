from typing import Any, Dict, List
from backend.repositories.evidence import CitationRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class CitationBuilder:
    """
    Links Claims to Evidence items by creating Citation records.

    Strategy: each claim is linked to the top MAX_EVIDENCE_PER_CLAIM evidence items.
    """

    MAX_EVIDENCE_PER_CLAIM = 3

    def __init__(self, citation_repository: CitationRepository):
        self._citation_repo = citation_repository

    async def build(
        self,
        claim_ids: List[str],
        evidence_ids: List[str],
        retrieved_chunks: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Create Citation records linking each claim to the top evidence items.
        Returns list of created Citation IDs.
        """
        if not claim_ids or not evidence_ids:
            return []

        # Build evidence_id → chunk data map
        chunk_map: Dict[str, Dict[str, Any]] = {}
        for chunk, eid in zip(retrieved_chunks, evidence_ids):
            chunk_map[eid] = chunk

        # Take top N evidence items
        top_evidence = evidence_ids[:self.MAX_EVIDENCE_PER_CLAIM]

        citation_ids: List[str] = []
        for claim_id in claim_ids:
            for evidence_id in top_evidence:
                chunk_data = chunk_map.get(evidence_id, {})
                try:
                    citation = await self._citation_repo.create(
                        claim_id=claim_id,
                        evidence_id=evidence_id,
                        excerpt=chunk_data.get("text", "")[:300],
                        relevance_score=chunk_data.get("score"),
                    )
                    citation_ids.append(str(citation.id))
                except Exception as exc:
                    logger.error("citation_create_failed", error=str(exc))

        logger.info(
            "citations_built",
            claims=len(claim_ids),
            evidence=len(top_evidence),
            citations=len(citation_ids),
        )
        return citation_ids
