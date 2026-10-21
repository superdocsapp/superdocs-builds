"""Provides the httpx.AsyncClient used to talk to SuperDocs, as a FastAPI
dependency so tests can override it with a mock-transport client instead of
making live network calls.
"""

from __future__ import annotations

import httpx


async def get_superdocs_http_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient() as client:
        yield client
