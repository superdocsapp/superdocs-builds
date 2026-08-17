import pytest
from core.superdocs_client import MockSuperDocsClient


class TestSuperDocsClient:
    @pytest.fixture
    def client(self):
        return MockSuperDocsClient(session_id="test-session")

    @pytest.mark.asyncio
    async def test_chat_async_returns_job_id(self, client):
        job_id = await client.chat_async("test message")
        assert job_id.startswith("job-mock-")

    @pytest.mark.asyncio
    async def test_get_job_returns_awaiting_approval(self, client):
        result = await client.get_job("job-123")
        assert result["status"] == "awaiting_approval"
        assert result["metadata"]["awaiting_kind"] == "change"
        assert len(result["metadata"]["pending_changes"]) == 1

    @pytest.mark.asyncio
    async def test_approve_change_returns_approved(self, client):
        result = await client.approve_change("job-1", "change-1", approved=True)
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_request_download_url_returns_url(self, client):
        url = await client.request_download_url(format="docx")
        assert url.endswith(".docx")
        assert "download.mock" in url

    @pytest.mark.asyncio
    async def test_get_document_detail_returns_structure(self, client):
        detail = await client.get_document_detail("doc-1")
        assert detail["section_count"] == 3
        assert detail["block_count"] == 5
        assert len(detail["headings"]) == 1