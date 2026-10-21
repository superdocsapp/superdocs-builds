"""
Load Product Specification Content Stage.

Loads text content from product specification documents.
"""

from typing import Dict, Any
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.repositories.document import DocumentRepository
from backend.storage.backend import StorageBackend
from backend.logging_config import get_logger

logger = get_logger(__name__)


class LoadProductContentStage(StageNode[TariffWorkflowState]):
    """Load product specification text content."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        storage: StorageBackend,
    ):
        super().__init__("load_product_content")
        self._doc_repo = document_repository
        self._storage = storage

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        """
        Load product specification content.

        Prefers product_spec documents over primary document.

        Args:
            state: Workflow state with product_spec_document_ids

        Returns:
            Dict with product_spec_content
        """
        product_spec_ids = state.product_spec_document_ids

        if not product_spec_ids:
            logger.info("no_product_spec_documents_using_primary")
            # Fallback to primary document if no product_spec documents
            return {
                "product_spec_content": state.document_content or "",
                "load_product_content_completed": True,
            }

        # Use first product_spec document (in future could handle multiple)
        product_spec_id = UUID(product_spec_ids[0])

        logger.info("loading_product_spec_content", document_id=str(product_spec_id))

        document = await self._doc_repo.get_by_id(product_spec_id)
        if not document:
            logger.warning("product_spec_document_not_found", document_id=str(product_spec_id))
            return {
                "product_spec_content": state.document_content or "",
                "load_product_content_completed": True,
            }

        # Extract text
        content = await self._extract_text(document)

        logger.info(
            "product_spec_content_loaded",
            document_id=str(product_spec_id),
            content_length=len(content),
        )

        return {
            "product_spec_content": content,
            "load_product_content_completed": True,
        }

    async def _extract_text(self, document) -> str:
        """Extract plain text from document."""
        try:
            content_bytes = self._storage.read(document.storage_path)
        except Exception as e:
            logger.error(
                "document_read_failed",
                path=document.storage_path,
                error=str(e),
            )
            return ""

        mime = (document.mime_type or "").lower()

        if mime == "text/plain" or document.filename.endswith(".txt"):
            try:
                return content_bytes.decode("utf-8", errors="replace")
            except Exception:
                return ""

        if mime == "application/pdf" or document.filename.endswith(".pdf"):
            try:
                from pypdf import PdfReader
                from io import BytesIO

                pdf = PdfReader(BytesIO(content_bytes))
                text_parts = []
                for page in pdf.pages:
                    text_parts.append(page.extract_text())
                return "\n\n".join(text_parts)
            except Exception as e:
                logger.error("pdf_extraction_failed", error=str(e))
                return ""

        # Unsupported mime type
        logger.warning("unsupported_mime_type", mime=mime, filename=document.filename)
        return ""
