import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock
from uuid import uuid4, UUID
from datetime import datetime, timezone
from io import BytesIO

from backend.main import app
from backend.models.document import Document
from backend.api.v1.documents import get_document_service


@pytest.mark.asyncio
async def test_upload_document():
    """Test POST /api/v1/documents handler"""
    from unittest.mock import MagicMock
    from backend.api.v1.documents import upload_document
    from backend.models.workspace import Workspace

    mock_service = AsyncMock()
    workspace_id = uuid4()
    document_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_document = Document(
        id=document_id,
        workspace_id=workspace_id,
        filename="test.pdf",
        storage_path="workspace-id/test_hash.pdf",
        mime_type="application/pdf",
        checksum="abc123",
        processing_status="pending",
        document_role="product_spec",
        created_at=now,
        updated_at=now,
    )
    mock_service.upload_document.return_value = mock_document

    workspace = Workspace(
        id=workspace_id,
        name="Upload Test Workspace",
        owner_user_id=uuid4(),
        status="active",
    )

    upload_file = MagicMock()
    upload_file.filename = "test.pdf"
    upload_file.content_type = "application/pdf"
    upload_file.read = AsyncMock(return_value=b"test content")

    result = await upload_document(
        workspace_id=workspace_id,
        file=upload_file,
        role="product_spec",
        workspace=workspace,
        service=mock_service,
    )

    assert result.filename == "test.pdf"
    assert result.workspace_id == workspace_id
    assert result.mime_type == "application/pdf"
    assert result.processing_status == "pending"
    mock_service.upload_document.assert_called_once()


@pytest.mark.asyncio
async def test_list_documents():
    """Test GET /api/v1/documents/workspace/{workspace_id}"""
    mock_service = AsyncMock()
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_service.list_workspace_documents.return_value = [
        Document(
            id=uuid4(),
            workspace_id=workspace_id,
            filename="doc1.pdf",
            storage_path="path/doc1.pdf",
            mime_type="application/pdf",
            checksum="abc123",
            processing_status="completed",
            document_role="product_spec",
            created_at=now,
            updated_at=now
        ),
        Document(
            id=uuid4(),
            workspace_id=workspace_id,
            filename="doc2.pdf",
            storage_path="path/doc2.pdf",
            mime_type="application/pdf",
            checksum="def456",
            processing_status="pending",
            document_role="product_spec",
            created_at=now,
            updated_at=now
        )
    ]

    app.dependency_overrides[get_document_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/documents/workspace/{workspace_id}")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["filename"] == "doc1.pdf"
            assert data[1]["filename"] == "doc2.pdf"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_document():
    """Test GET /api/v1/documents/{document_id}"""
    document_id = uuid4()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/documents/{document_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test.pdf"
        assert data["id"] == str(document_id)


@pytest.mark.asyncio
async def test_get_document_not_found():
    """Test GET /api/v1/documents/{document_id} with non-existent ID"""
    from fastapi import HTTPException, status
    from backend.api.deps import verify_document_workspace_access

    document_id = uuid4()

    async def deny_document(document_id: UUID):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )

    app.dependency_overrides[verify_document_workspace_access] = deny_document

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/documents/{document_id}")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(verify_document_workspace_access, None)


@pytest.mark.asyncio
async def test_download_document():
    """Test GET /api/v1/documents/{document_id}/content"""
    mock_service = AsyncMock()
    document_id = uuid4()
    mock_service.get_document_content.return_value = b"file content"

    app.dependency_overrides[get_document_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/documents/{document_id}/content")

            assert response.status_code == 200
            assert response.content == b"file content"
            assert response.headers["content-type"] == "application/pdf"
            assert 'attachment; filename="test.pdf"' in response.headers["content-disposition"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_download_document_not_found():
    """Test GET /api/v1/documents/{document_id}/content with non-existent ID"""
    from fastapi import HTTPException, status
    from backend.api.deps import verify_document_workspace_access

    document_id = uuid4()

    async def deny_document(document_id: UUID):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )

    app.dependency_overrides[verify_document_workspace_access] = deny_document

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/documents/{document_id}/content")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(verify_document_workspace_access, None)


@pytest.mark.asyncio
async def test_download_document_content_error():
    """Test GET /api/v1/documents/{document_id}/content with storage error"""
    mock_service = AsyncMock()
    document_id = uuid4()
    mock_service.get_document_content.return_value = None

    app.dependency_overrides[get_document_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/documents/{document_id}/content")

            assert response.status_code == 500
            assert "failed to retrieve" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_document():
    """Test DELETE /api/v1/documents/{document_id}"""
    mock_service = AsyncMock()
    document_id = uuid4()

    mock_service.delete_document.return_value = True

    app.dependency_overrides[get_document_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/v1/documents/{document_id}")

            assert response.status_code == 204
            assert response.content == b''
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upload_document_invalid_role():
    """Test upload rejects invalid document role."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException
    from backend.api.v1.documents import upload_document
    from backend.models.workspace import Workspace

    mock_service = AsyncMock()
    workspace = Workspace(
        id=uuid4(),
        name="Test",
        owner_user_id=uuid4(),
        status="active",
    )
    upload_file = MagicMock()
    upload_file.filename = "test.pdf"
    upload_file.content_type = "application/pdf"
    upload_file.read = AsyncMock(return_value=b"content")

    with pytest.raises(HTTPException) as exc_info:
        await upload_document(
            workspace_id=workspace.id,
            file=upload_file,
            role="invalid_role",
            workspace=workspace,
            service=mock_service,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_document_not_found():
    """Test DELETE /api/v1/documents/{document_id} with non-existent ID"""
    mock_service = AsyncMock()
    document_id = uuid4()

    mock_service.delete_document.return_value = False

    app.dependency_overrides[get_document_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/v1/documents/{document_id}")

            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
