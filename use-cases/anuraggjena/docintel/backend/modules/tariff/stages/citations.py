from typing import Any, Dict

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.core.retrieval.citations import CitationBuilder
from backend.logging_config import get_logger

logger = get_logger(__name__)


class CitationBuilderStage(StageNode[TariffWorkflowState]):
    """
    Links Claim records to Evidence records by creating Citation records.
    Runs after GenerateStage.
    """

    def __init__(self, citation_builder: CitationBuilder):
        super().__init__("citations")
        self._builder = citation_builder

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        claim_ids = state.claim_ids or []
        evidence_ids = state.evidence_ids or []
        retrieved_chunks = state.retrieved_chunks or []

        if not claim_ids:
            logger.info("citations_stage_skipped", reason="no claims")
            return {"citations_completed": True, "citation_ids": []}

        citation_ids = await self._builder.build(
            claim_ids=claim_ids,
            evidence_ids=evidence_ids,
            retrieved_chunks=retrieved_chunks,
        )

        logger.info("citations_stage_complete", citations=len(citation_ids))
        return {
            "citations_completed": True,
            "citation_ids": citation_ids,
        }
