"""
Load Ruling Content Stage.

Loads text content from ruling documents.
"""

from typing import Dict, Any
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.repositories.document import DocumentRepository
from backend.storage.backend import StorageBackend
from backend.logging_config import get_logger

logger = get_logger(__name__)


class LoadRulingContentStage(StageNode[TariffWorkflowState]):
    """Load ruling document text content."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        storage: StorageBackend,
    ):
        super().__init__("load_ruling_content")
        self._doc_repo = document_repository
        self._storage = storage

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        """
        Load ruling document content.

        Args:
            state: Workflow state with ruling_document_ids

        Returns:
            Dict with ruling_content_map
        """
        ruling_ids = state.ruling_document_ids

        if not ruling_ids:
            logger.info("no_ruling_documents")
            return {
                "ruling_content_map": {},
                "load_ruling_content_completed": True,
            }

        logger.info("loading_ruling_content", ruling_count=len(ruling_ids))

        ruling_content_map = {}

        for ruling_id_str in ruling_ids:
            ruling_id = UUID(ruling_id_str)
            document = await self._doc_repo.get_by_id(ruling_id)

            if not document:
                logger.warning("ruling_document_not_found", document_id=ruling_id_str)
                continue

            content = await self._extract_text(document)

            if content:
                ruling_content_map[ruling_id_str] = content
                logger.info(
                    "ruling_content_loaded",
                    document_id=ruling_id_str,
                    content_length=len(content),
                )

        logger.info("ruling_content_loading_complete", loaded=len(ruling_content_map))

        return {
            "ruling_content_map": ruling_content_map,
            "load_ruling_content_completed": True,
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

        logger.warning("unsupported_mime_type", mime=mime, filename=document.filename)
        return ""
