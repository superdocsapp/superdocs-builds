"""
SuperDocs Upload Stage.

Uploads the document to SuperDocs and creates a session at the start of the workflow.
"""

import base64
from uuid import UUID
from typing import Dict, Any

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.integrations.superdocs import SuperDocsClient, SessionManager, DocumentBridge
from backend.repositories.document import DocumentRepository
from backend.storage.backend import StorageBackend
from backend.logging_config import get_logger

logger = get_logger(__name__)


class SuperDocsUploadStage(StageNode[TariffWorkflowState]):
    """
    Upload document to SuperDocs and create editing session.

    This stage:
    1. Retrieves document from DocIntel storage
    2. Uploads to SuperDocs (base64 for small files, pre-signed URL for large files)
    3. Creates SuperDocs session
    4. Stores session mapping in database
    """

    def __init__(
        self,
        superdocs_client: SuperDocsClient,
        session_manager: SessionManager,
        document_bridge: DocumentBridge,
        document_repository: DocumentRepository,
        storage: StorageBackend
    ):
        # Don't call super().__init__() - name is defined as @property
        self.superdocs_client = superdocs_client
        self.session_manager = session_manager
        self.document_bridge = document_bridge
        self.document_repository = document_repository
        self.storage = storage

    @property
    def name(self) -> str:
        return "superdocs_upload"

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        """
        Upload document to SuperDocs and create session.

        Args:
            state: Current workflow state

        Returns:
            Updated state with superdocs_session_id and superdocs_document_id
        """
        run_id = UUID(state.workflow_run_id)
        document_id = UUID(state.document_id)

        logger.info(
            "superdocs_upload_starting",
            run_id=str(run_id),
            document_id=str(document_id)
        )

        # Get document from database
        document = await self.document_repository.get_by_id(document_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        # Read document content from storage
        try:
            content_bytes = self.storage.read(document.storage_path)
        except Exception as exc:
            logger.error(
                "document_read_failed",
                path=document.storage_path,
                error=str(exc)
            )
            raise ValueError(f"Failed to read document: {str(exc)}") from exc

        # Determine upload method based on file size
        file_size = len(content_bytes)
        use_base64 = file_size < 100 * 1024  # 100KB threshold

        logger.info(
            "superdocs_upload_method_selected",
            file_size=file_size,
            method="base64" if use_base64 else "pre_signed_url"
        )

        # Create SuperDocs session first (needed for document upload)
        superdocs_session_id = await self.session_manager.create_session_for_run(
            run_id=run_id
        )

        logger.info(
            "superdocs_session_created",
            session_id=superdocs_session_id
        )

        # Upload document to SuperDocs
        if use_base64:
            # Small file: use base64 upload
            file_base64 = base64.b64encode(content_bytes).decode('utf-8')

            process_result = await self.superdocs_client.upload_document_base64(
                filename=document.filename,
                file_base64=file_base64,
                session_id=superdocs_session_id
            )

            superdocs_document_id = process_result.document_id

        else:
            # Large file: use pre-signed URL upload
            upload_url_result = await self.superdocs_client.request_upload_url(
                filename=document.filename,
                content_type=document.mime_type or "application/octet-stream",
                size_bytes=file_size
            )

            # Upload file to pre-signed URL
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    upload_url_result.upload_url,
                    content=content_bytes,
                    headers={"Content-Type": document.mime_type or "application/octet-stream"}
                )
                response.raise_for_status()

            # Process uploaded document
            process_result = await self.superdocs_client.process_uploaded_document(
                upload_id=upload_url_result.upload_id,
                session_id=superdocs_session_id,
                filename=document.filename
            )

            superdocs_document_id = process_result.document_id

        # Update session with document ID
        await self.session_manager.repo.update_document_id(
            workflow_run_id=run_id,
            superdocs_document_id=superdocs_document_id
        )

        logger.info(
            "superdocs_upload_complete",
            run_id=str(run_id),
            session_id=superdocs_session_id,
            document_id=superdocs_document_id,
            chunks_count=process_result.chunks_count
        )

        # Return state updates
        return {
            "superdocs_session_id": superdocs_session_id,
            "superdocs_document_id": superdocs_document_id
        }
