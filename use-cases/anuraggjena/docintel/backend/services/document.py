from uuid import UUID
from typing import List, Optional
import hashlib

from backend.repositories.document import DocumentRepository
from backend.storage.backend import StorageBackend
from backend.models.document import Document
from backend.logging_config import get_logger

logger = get_logger(__name__)


class DocumentService:
    def __init__(self, repository: DocumentRepository, storage: StorageBackend):
        self.repository = repository
        self.storage = storage

    async def upload_document(
        self,
        workspace_id: UUID,
        filename: str,
        content: bytes,
        mime_type: str,
        document_role: str = "product_spec",
    ) -> Document:
        """Upload a document to storage and create database record"""
        logger.info("uploading_document", workspace_id=str(workspace_id), filename=filename)

        # Calculate checksum for deduplication
        checksum = hashlib.sha256(content).hexdigest()

        # Check if document already exists in this workspace
        existing = await self.repository.get_by_checksum(workspace_id, checksum)
        if existing:
            logger.info("document_already_exists", document_id=str(existing.id))
            return existing

        # Store file
        storage_path = self.storage.save(content, filename, str(workspace_id))

        # Create database record
        document = await self.repository.create(
            workspace_id=workspace_id,
            filename=filename,
            storage_path=storage_path,
            mime_type=mime_type,
            checksum=checksum,
            processing_status="pending",
            document_role=document_role,
        )

        logger.info("document_uploaded", document_id=str(document.id))
        return document

    async def get_document(self, document_id: UUID) -> Optional[Document]:
        """Get document by ID"""
        return await self.repository.get_by_id(document_id)

    async def list_workspace_documents(self, workspace_id: UUID) -> List[Document]:
        """List all documents in a workspace"""
        return await self.repository.list_by_workspace(workspace_id)

    async def delete_document(self, document_id: UUID) -> bool:
        """Delete document and its file from storage"""
        document = await self.repository.get_by_id(document_id)
        if not document:
            return False

        # Delete from storage
        try:
            self.storage.delete(document.storage_path)
        except Exception as e:
            logger.error("storage_delete_failed", error=str(e), path=document.storage_path)

        # Delete from database
        success = await self.repository.delete(document_id)

        if success:
            logger.info("document_deleted", document_id=str(document_id))

        return success

    async def get_document_content(self, document_id: UUID) -> Optional[bytes]:
        """Retrieve document content from storage"""
        document = await self.repository.get_by_id(document_id)
        if not document:
            return None

        try:
            return self.storage.read(document.storage_path)
        except Exception as e:
            logger.error("storage_read_failed", error=str(e), document_id=str(document_id))
            return None
