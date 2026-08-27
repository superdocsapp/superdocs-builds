import httpx
import pytest
from pydantic import SecretStr

from series_bible.application.llm import LLMProviderError, OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_invalid_api_key_raises_clear_error_without_retrying(monkeypatch):
    calls = []

    async def fake_post(self, url, headers=None, json=None):
        calls.append(url)
        return httpx.Response(
            401,
            request=httpx.Request("POST", url),
            json={"error": {"message": "Incorrect API key provided"}},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = OpenAICompatibleProvider("https://api.openai.com/v1", SecretStr("bad-key"), "gpt-4.1-mini")

    with pytest.raises(LLMProviderError, match="401"):
        await provider.extract_facts("Elena has green eyes.")

    # A 401 is not a transient failure, so it must fail on the first attempt
    # rather than exhausting the configured retry budget.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_server_error_raises_clear_error(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        return httpx.Response(500, request=httpx.Request("POST", url), text="upstream failure")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    provider = OpenAICompatibleProvider("https://api.openai.com/v1", SecretStr("key"), "gpt-4.1-mini")

    with pytest.raises(LLMProviderError, match="500"):
        await provider.extract_facts("Elena has green eyes.")
