from __future__ import annotations

from typing import Any

import httpx

from config.env import get_settings


class SuperDocsError(Exception):
    pass


def declaration_instruction(html: str) -> str:
    return f"Append the exact HTML block below at the very end of the manuscript as one insertion. Do not edit, replace, match, reuse, or infer from existing manuscript text. Do not split the block into separate edits. Do not change any wording.\n\n{html}"


async def provider_request(method: str, path: str, payload: dict[str, Any] | None = None) -> httpx.Response:
    settings = get_settings()
    if not settings.superdocs_api_key:
        raise SuperDocsError("SUPERDOCS_NOT_CONFIGURED")
    try:
        timeout = httpx.Timeout(settings.superdocs_timeout_ms / 1000)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                f"{settings.superdocs_base_url}{path}",
                headers={"Authorization": f"Bearer {settings.superdocs_api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            return response
    except httpx.HTTPError as error:
        raise SuperDocsError("SUPERDOCS_PROVIDER_FAILED") from error
