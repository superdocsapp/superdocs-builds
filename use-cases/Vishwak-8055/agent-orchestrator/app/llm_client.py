"""Pluggable LLM client.

Specialist agents that need model calls depend on this interface,
not on any specific SDK. StubLLMClient is deterministic and used
in tests and local dev; swap in a real Vertex AI / Gemini client in
production by implementing the same complete() method.
"""
from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    async def complete(self, prompt: str) -> str: ...


class StubLLMClient:
    """Deterministic stand-in -- no network calls, safe for tests."""

    async def complete(self, prompt: str) -> str:
        return f"[stub response for prompt of {len(prompt)} chars]"
