import pytest
from core.llm_provider import MockLLMProvider


class TestMockLLMProvider:
    @pytest.fixture
    def mock_llm(self):
        return MockLLMProvider()

    @pytest.mark.asyncio
    async def test_record_and_replay(self, mock_llm):
        from pydantic import BaseModel

        class TestSchema(BaseModel):
            value: str

        mock_llm.record("test prompt", "TestSchema", {"value": "hello"})
        result = await mock_llm.complete("test prompt", TestSchema)
        assert result.value == "hello"

    @pytest.mark.asyncio
    async def test_embed_replay(self, mock_llm):
        mock_llm.record_embedding("hello world", [0.1, 0.2, 0.3] + [0.0] * 1533)
        result = await mock_llm.embed("hello world")
        assert len(result) == 1536
        assert result[0] == 0.1

    @pytest.mark.asyncio
    async def test_missing_returns_default(self, mock_llm):
        from pydantic import BaseModel

        class TestSchema(BaseModel):
            value: str = ""

        result = await mock_llm.complete("unknown prompt", TestSchema)
        assert result.value == ""

    @pytest.mark.asyncio
    async def test_default_embedding_is_zero_vector(self, mock_llm):
        result = await mock_llm.embed("unknown text")
        assert result == [0.0] * 1536