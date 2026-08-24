"""Shared FastAPI dependencies for the API routers."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.integrations.superdocs.client import SuperDocsClient


def require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    """Costly endpoints REQUIRE an Idempotency-Key so retries are safe."""
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required 'Idempotency-Key' header.",
        )
    return idempotency_key.strip()


def get_superdocs_client(settings: Settings = Depends(get_settings)) -> SuperDocsClient:
    """Real client. Overridden in tests with a fake (no network, no key)."""
    return SuperDocsClient(
        base_url=settings.superdocs_base_url,
        api_key=settings.superdocs_api_key,
        timeout_seconds=settings.superdocs_timeout_seconds,
    )
