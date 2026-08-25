"""
Document Discovery Stage for Tariff Workflow.

Discovers and categorizes all relevant documents in the workspace
before extraction begins.
"""

from typing import Dict, Any, List
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.repositories.document import DocumentRepository
from backend.logging_config import get_logger

logger = get_logger(__name__)


class DiscoverDocumentsStage(StageNode[TariffWorkflowState]):
    """
    Discover all workspace documents and categorize by role.

    Identifies:
    - Product specifications
    - Classification rulings
    - Product images
    - Other supporting documents
    """

    def __init__(self, document_repository: DocumentRepository):
        super().__init__("discover_documents")
        self._doc_repo = document_repository

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        """
        Discover and categorize workspace documents.

        Args:
            state: Workflow state with workspace_id

        Returns:
            Dict with discovered document IDs and flags
        """
        workspace_id = UUID(state.workspace_id)

        logger.info("discovering_workspace_documents", workspace_id=str(workspace_id))

        # Get all documents in workspace
        all_docs = await self._doc_repo.list_by_workspace(workspace_id)

        # Categorize by role
        product_specs = [d for d in all_docs if d.document_role == "product_spec"]
        rulings = [d for d in all_docs if d.document_role == "ruling"]
        images = [d for d in all_docs if d.document_role == "product_image"]
        others = [d for d in all_docs if d.document_role == "other"]

        logger.info(
            "documents_discovered",
            workspace_id=str(workspace_id),
            product_specs=len(product_specs),
            rulings=len(rulings),
            images=len(images),
            others=len(others),
        )

        # Build document ID lists
        product_spec_ids = [str(d.id) for d in product_specs]
        ruling_ids = [str(d.id) for d in rulings]
        image_ids = [str(d.id) for d in images]
        other_ids = [str(d.id) for d in others]

        # Workspace document IDs (all documents)
        workspace_doc_ids = [str(d.id) for d in all_docs]

        return {
            "product_spec_document_ids": product_spec_ids,
            "ruling_document_ids": ruling_ids,
            "image_document_ids": image_ids,
            "other_document_ids": other_ids,
            "workspace_document_ids": workspace_doc_ids,
            "has_ruling_documents": len(rulings) > 0,
            "discover_documents_completed": True,
        }
