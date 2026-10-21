import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from backend.services.document import DocumentService
from backend.models.document import Document


@pytest.fixture
def mock_document_repo():
    """Mock document repository for service tests"""
    from backend.repositories.document import DocumentRepository

    mock = AsyncMock(spec=DocumentRepository)
    return mock


@pytest.fixture
def mock_storage():
    """Mock storage backend for service tests"""
    from backend.storage.backend import StorageBackend

    mock = MagicMock(spec=StorageBackend)
    mock.save.return_value = "workspace-id/test_file_hash.pdf"
    mock.read.return_value = b"file content"
    return mock


@pytest.mark.asyncio
async def test_upload_document_service(mock_document_repo, mock_storage):
    """Test document upload via service"""
    service = DocumentService(mock_document_repo, mock_storage)
    workspace_id = uuid4()

    # Mock no existing document (no deduplication)
    mock_document_repo.get_by_checksum.return_value = None

    # Mock create result
    document_mock = MagicMock(spec=Document)
    document_mock.id = uuid4()
    document_mock.filename = "test.pdf"
    document_mock.workspace_id = workspace_id
    document_mock.mime_type = "application/pdf"
    document_mock.processing_status = "pending"
    mock_document_repo.create.return_value = document_mock

    result = await service.upload_document(
        workspace_id=workspace_id,
        filename="test.pdf",
        content=b"test content",
        mime_type="application/pdf"
    )

    assert result.filename == "test.pdf"
    mock_storage.save.assert_called_once()
    mock_document_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_upload_document_deduplication(mock_document_repo, mock_storage):
    """Test document deduplication on upload"""
    service = DocumentService(mock_document_repo, mock_storage)
    workspace_id = uuid4()

    # Mock existing document with same checksum
    existing_doc = MagicMock(spec=Document)
    existing_doc.id = uuid4()
    existing_doc.workspace_id = workspace_id
    existing_doc.filename = "existing.pdf"
    mock_document_repo.get_by_checksum.return_value = existing_doc

    result = await service.upload_document(
        workspace_id=workspace_id,
        filename="duplicate.pdf",
        content=b"test content",
        mime_type="application/pdf"
    )

    # Should return existing document
    assert result.id == existing_doc.id
    # Should not save to storage or create new record
    mock_storage.save.assert_not_called()
    mock_document_repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_upload_document_different_workspace_same_checksum(mock_document_repo, mock_storage):
    """Test that identical content in different workspaces creates separate documents"""
    service = DocumentService(mock_document_repo, mock_storage)
    workspace_1 = uuid4()
    workspace_2 = uuid4()

    # First upload to workspace 1 - no existing document
    mock_document_repo.get_by_checksum.return_value = None
    mock_storage.save.return_value = "/storage/workspace1/test.pdf"

    created_doc_1 = Document(
        id=uuid4(),
        workspace_id=workspace_1,
        filename="test.pdf",
        storage_path="/storage/workspace1/test.pdf",
        mime_type="application/pdf",
        checksum="abc123",
        processing_status="pending"
    )
    mock_document_repo.create.return_value = created_doc_1

    doc1 = await service.upload_document(
        workspace_id=workspace_1,
        filename="test.pdf",
        content=b"test content",
        mime_type="application/pdf"
    )

    assert doc1.id == created_doc_1.id
    assert mock_document_repo.create.call_count == 1

    # Second upload to workspace 2 with same content - should create new document
    mock_document_repo.get_by_checksum.return_value = None  # Different workspace, no match
    mock_storage.save.return_value = "/storage/workspace2/test.pdf"

    created_doc_2 = Document(
        id=uuid4(),
        workspace_id=workspace_2,
        filename="test.pdf",
        storage_path="/storage/workspace2/test.pdf",
        mime_type="application/pdf",
        checksum="abc123",  # Same checksum
        processing_status="pending"
    )
    mock_document_repo.create.return_value = created_doc_2

    doc2 = await service.upload_document(
        workspace_id=workspace_2,
        filename="test.pdf",
        content=b"test content",  # Same content
        mime_type="application/pdf"
    )

    assert doc2.id == created_doc_2.id
    assert doc2.id != doc1.id
    assert mock_document_repo.create.call_count == 2


@pytest.mark.asyncio
async def test_get_document_service(mock_document_repo, mock_storage):
    """Test getting document via service"""
    service = DocumentService(mock_document_repo, mock_storage)
    document_id = uuid4()

    mock_document_repo.get_by_id.return_value = Document(
        id=document_id,
        workspace_id=uuid4(),
        filename="test.pdf",
        storage_path="path/test.pdf",
        mime_type="application/pdf",
        checksum="abc123",
        processing_status="completed"
    )

    result = await service.get_document(document_id)

    assert result is not None
    assert result.id == document_id


@pytest.mark.asyncio
async def test_list_workspace_documents_service(mock_document_repo, mock_storage):
    """Test listing workspace documents via service"""
    service = DocumentService(mock_document_repo, mock_storage)
    workspace_id = uuid4()

    mock_document_repo.list_by_workspace.return_value = [
        Document(
            id=uuid4(),
            workspace_id=workspace_id,
            filename="doc1.pdf",
            storage_path="path/doc1.pdf",
            mime_type="application/pdf",
            checksum="abc123",
            processing_status="completed"
        ),
        Document(
            id=uuid4(),
            workspace_id=workspace_id,
            filename="doc2.pdf",
            storage_path="path/doc2.pdf",
            mime_type="application/pdf",
            checksum="def456",
            processing_status="pending"
        )
    ]

    result = await service.list_workspace_documents(workspace_id)

    assert len(result) == 2
    assert result[0].filename == "doc1.pdf"
    assert result[1].filename == "doc2.pdf"


@pytest.mark.asyncio
async def test_delete_document_service(mock_document_repo, mock_storage):
    """Test deleting document via service"""
    service = DocumentService(mock_document_repo, mock_storage)
    document_id = uuid4()

    # Mock document exists
    mock_document = MagicMock(spec=Document)
    mock_document.storage_path = "workspace-id/test.pdf"
    mock_document_repo.get_by_id.return_value = mock_document
    mock_document_repo.delete.return_value = True

    result = await service.delete_document(document_id)

    assert result is True
    mock_storage.delete.assert_called_once_with("workspace-id/test.pdf")
    mock_document_repo.delete.assert_called_once_with(document_id)


@pytest.mark.asyncio
async def test_delete_document_not_found(mock_document_repo, mock_storage):
    """Test deleting non-existent document"""
    service = DocumentService(mock_document_repo, mock_storage)
    document_id = uuid4()

    mock_document_repo.get_by_id.return_value = None

    result = await service.delete_document(document_id)

    assert result is False
    mock_storage.delete.assert_not_called()


@pytest.mark.asyncio
async def test_get_document_content_service(mock_document_repo, mock_storage):
    """Test getting document content via service"""
    service = DocumentService(mock_document_repo, mock_storage)
    document_id = uuid4()

    mock_document = MagicMock(spec=Document)
    mock_document.storage_path = "workspace-id/test.pdf"
    mock_document_repo.get_by_id.return_value = mock_document

    result = await service.get_document_content(document_id)

    assert result == b"file content"
    mock_storage.read.assert_called_once_with("workspace-id/test.pdf")


@pytest.mark.asyncio
async def test_get_document_content_not_found(mock_document_repo, mock_storage):
    """Test getting content of non-existent document"""
    service = DocumentService(mock_document_repo, mock_storage)
    document_id = uuid4()

    mock_document_repo.get_by_id.return_value = None

    result = await service.get_document_content(document_id)

    assert result is None
    mock_storage.read.assert_not_called()


@pytest.mark.asyncio
async def test_get_document_content_storage_error(mock_document_repo, mock_storage):
    """Test handling storage error when reading content"""
    service = DocumentService(mock_document_repo, mock_storage)
    document_id = uuid4()

    mock_document = MagicMock(spec=Document)
    mock_document.storage_path = "workspace-id/test.pdf"
    mock_document_repo.get_by_id.return_value = mock_document
    mock_storage.read.side_effect = FileNotFoundError("File not found")

    result = await service.get_document_content(document_id)

    assert result is None
