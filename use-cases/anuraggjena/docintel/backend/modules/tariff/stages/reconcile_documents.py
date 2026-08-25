"""
Reconcile Documents Stage.

Matches product facts with ruling facts to determine relevance.
"""

from typing import Dict, Any

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.document_reconciliation import DocumentReconciliation
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ReconcileDocumentsStage(StageNode[TariffWorkflowState]):
    """
    Reconcile product specifications with ruling documents.

    Determines which rulings are relevant based on extracted facts.
    """

    def __init__(self):
        super().__init__("reconcile_documents")
        self.reconciliation = DocumentReconciliation()

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        """
        Reconcile product and ruling facts.

        Args:
            state: Workflow state with product_facts and ruling_facts

        Returns:
            Dict with matched_ruling_ids and reconciliation details
        """
        logger.info(
            "starting_reconciliation",
            has_product_facts=bool(state.product_facts),
            ruling_facts_count=len(state.ruling_facts),
        )

        result = self.reconciliation.reconcile(
            product_facts=state.product_facts,
            ruling_facts=state.ruling_facts,
        )

        logger.info(
            "reconciliation_complete",
            matched_rulings=len(result["matched_ruling_ids"]),
            conflicts=len(result["conflicts"]),
        )

        return {
            "matched_ruling_ids": result["matched_ruling_ids"],
            "reconciliation_match_reasons": result["match_reasons"],
            "reconciliation_conflicts": result["conflicts"],
            "reconciliation_completed": True,
        }
