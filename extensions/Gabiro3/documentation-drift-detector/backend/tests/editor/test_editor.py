import pytest
from core.superdocs_client import MockSuperDocsClient


class TestEditor:
    @pytest.fixture
    def client(self):
        return MockSuperDocsClient(session_id="test-session")

    @pytest.mark.asyncio
    async def test_chat_async_called(self, client):
        job_id = await client.chat_async("test", approval_mode="ask_every_time", model_tier="max")
        assert job_id.startswith("job-mock-")

    @pytest.mark.asyncio
    async def test_get_job_pending_changes(self, client):
        job = await client.get_job("job-123")
        assert job["status"] == "awaiting_approval"
        changes = job["metadata"]["pending_changes"]
        assert len(changes) == 1
        assert "chunk_id" in changes[0]

    @pytest.mark.asyncio
    async def test_approve_change(self, client):
        result = await client.approve_change("job-1", "change-1", approved=True)
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_deny_change(self, client):
        result = await client.approve_change("job-1", "change-1", approved=False, feedback="Wrong chunk")
        assert result["status"] == "approved"  # API responds ok regardless