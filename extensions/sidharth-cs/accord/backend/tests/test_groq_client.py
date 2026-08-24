"""Groq 429 rate-limit retry tests — bounded backoff, explicit exhaustion."""

import asyncio

import httpx

from app.transcript.groq_client import GroqRateLimitExhausted, GroqSTTClient


class StubTransport(httpx.AsyncBaseTransport):
    """Serves a scripted sequence of httpx responses (status codes)."""

    def __init__(self, statuses: list[int]):
        self.statuses = statuses
        self.requests = 0

    async def handle_async_request(self, request):
        self.requests += 1
        status = self.statuses.pop(0)
        return httpx.Response(
            status,
            request=request,
            json={"text": "hello from groq"} if status == 200 else {"error": "rate limited"},
            headers={"retry-after": "0"},  # avoid real waiting in tests
        )


def _samples():
    return [0] * 16000  # 1s of silence, shape-only


def _client(statuses):
    transport = StubTransport(statuses)
    client = GroqSTTClient(api_key="test", timeout=5.0, transport=transport)
    return client, transport


def test_429_then_success_retries_and_transcribes():
    client, transport = _client([429, 200])

    async def run():
        return await client.transcribe(_samples(), 16000)

    text = asyncio.run(run())
    assert text == "hello from groq"
    assert transport.requests == 2  # one retry, exactly — no duplication


def test_429_exhaustion_raises_distinguished_exception():
    client, transport = _client([429, 429, 429])

    async def run():
        try:
            await client.transcribe(_samples(), 16000)
        except GroqRateLimitExhausted:
            return True
        return False

    exhausted = asyncio.run(run())
    assert exhausted is True
    assert transport.requests == 3  # bounded: exactly the retry budget, no more
