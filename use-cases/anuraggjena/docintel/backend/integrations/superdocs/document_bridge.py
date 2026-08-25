"""
SuperDocs Document Bridge.

Syncs document content between DocIntel and SuperDocs.
"""

import base64
from pathlib import Path
from typing import Optional, List
from uuid import UUID

from backend.integrations.superdocs.client import SuperDocsClient
from backend.integrations.superdocs.session_manager import SessionManager
from backend.repositories.document import DocumentRepository
from backend.models.document import DocumentChunk
from backend.logging_config import get_logger

logger = get_logger(__name__)


class DocumentBridge:
    """
    Bridges DocIntel documents with SuperDocs content layer.

    Responsibilities:
    - Upload DocIntel documents to SuperDocs
    - Extract text from SuperDocs HTML for chunking
    - Sync document content between systems
    """

    def __init__(
        self,
        superdocs_client: SuperDocsClient,
        session_manager: SessionManager,
        document_repository: DocumentRepository
    ):
        """
        Initialize document bridge.

        Args:
            superdocs_client: SuperDocs API client
            session_manager: Session lifecycle manager
            document_repository: DocIntel document repository
        """
        self.client = superdocs_client
        self.session_manager = session_manager
        self.doc_repo = document_repository

    async def upload_document(
        self,
        document_id: UUID,
        file_path: str,
        run_id: UUID
    ) -> str:
        """
        Upload document to SuperDocs and associate with session.

        Args:
            document_id: DocIntel document ID
            file_path: Path to document file
            run_id: Workflow run ID

        Returns:
            SuperDocs document ID

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is too large or unsupported format
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        file_size = path.stat().st_size
        filename = path.name

        # Determine upload method based on file size
        if file_size > 100 * 1024:  # >100KB: use pre-signed URL
            logger.info(
                "uploading_large_document",
                document_id=str(document_id),
                size_bytes=file_size
            )

            superdocs_doc_id = await self._upload_large_document(
                file_path=file_path,
                filename=filename,
                file_size=file_size,
                run_id=run_id
            )
        else:  # <=100KB: use base64 inline
            logger.info(
                "uploading_small_document",
                document_id=str(document_id),
                size_bytes=file_size
            )

            superdocs_doc_id = await self._upload_small_document(
                file_path=file_path,
                filename=filename,
                run_id=run_id
            )

        # Update session with document ID
        await self.session_manager.update_session_document(run_id, superdocs_doc_id)

        logger.info(
            "document_uploaded_to_superdocs",
            docintel_doc_id=str(document_id),
            superdocs_doc_id=superdocs_doc_id
        )

        return superdocs_doc_id

    async def _upload_small_document(
        self,
        file_path: str,
        filename: str,
        run_id: UUID
    ) -> str:
        """Upload small document via base64."""
        # Read file and encode
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        file_base64 = base64.b64encode(file_bytes).decode("utf-8")

        # Get or create session
        session_id = await self.session_manager.get_or_create_session(run_id)

        # Upload to SuperDocs
        result = await self.client.upload_document_base64(
            filename=filename,
            file_base64=file_base64,
            session_id=session_id
        )

        return result.document_id

    async def _upload_large_document(
        self,
        file_path: str,
        filename: str,
        file_size: int,
        run_id: UUID
    ) -> str:
        """Upload large document via pre-signed URL."""
        # Determine content type
        content_type = self._get_content_type(filename)

        # Request upload URL
        upload_result = await self.client.request_upload_url(
            filename=filename,
            content_type=content_type,
            size_bytes=file_size
        )

        # Upload file to pre-signed URL
        # Note: This would use httpx or similar in production
        logger.info(
            "uploading_to_presigned_url",
            upload_id=upload_result.upload_id
        )

        # TODO: Implement actual file upload via httpx
        # For now, document the expected behavior
        # with open(file_path, "rb") as f:
        #     await httpx.put(upload_result.upload_url, content=f.read())

        # Get or create session
        session_id = await self.session_manager.get_or_create_session(run_id)

        # Process uploaded document
        process_result = await self.client.process_uploaded_document(
            upload_id=upload_result.upload_id,
            session_id=session_id,
            filename=filename
        )

        return process_result.document_id

    def _get_content_type(self, filename: str) -> str:
        """Determine MIME type from filename."""
        ext = Path(filename).suffix.lower()

        content_types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".txt": "text/plain",
            ".rtf": "application/rtf",
            ".md": "text/markdown",
            ".html": "text/html",
            ".htm": "text/html",
        }

        return content_types.get(ext, "application/octet-stream")

    async def extract_chunks_from_html(
        self,
        superdocs_doc_id: str,
        run_id: UUID
    ) -> List[DocumentChunk]:
        """
        Extract text chunks from SuperDocs HTML for DocIntel processing.

        Args:
            superdocs_doc_id: SuperDocs document ID
            run_id: Workflow run ID

        Returns:
            List of DocumentChunk objects (not persisted)

        Note:
            This is a placeholder. In production, this would:
            1. Get document HTML from SuperDocs
            2. Parse HTML and extract text from chunks
            3. Return DocumentChunk objects for embedding
        """
        logger.info(
            "extracting_chunks_from_superdocs",
            superdocs_doc_id=superdocs_doc_id
        )

        # TODO: Implement chunk extraction from SuperDocs HTML
        # This requires:
        # 1. Get full document HTML from SuperDocs session
        # 2. Parse data-chunk-id attributes
        # 3. Extract text content from each chunk
        # 4. Create DocumentChunk objects

        return []

    async def sync_document_content(
        self,
        document_id: UUID,
        superdocs_doc_id: str
    ) -> None:
        """
        Sync document content from SuperDocs to DocIntel.

        Args:
            document_id: DocIntel document ID
            superdocs_doc_id: SuperDocs document ID

        Note:
            This would be used for focused updates to detect changes.
        """
        logger.info(
            "syncing_document_content",
            docintel_doc_id=str(document_id),
            superdocs_doc_id=superdocs_doc_id
        )

        # TODO: Implement content sync
        # This would:
        # 1. Get current SuperDocs HTML
        # 2. Compare with stored DocIntel chunks
        # 3. Identify changed chunks
        # 4. Update DocIntel database

        pass
