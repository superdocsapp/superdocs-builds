from __future__ import annotations

from typing import Any

import httpx

from routes.errors import failure
from utils.superdocs import SuperDocsError


def provider_json(response: httpx.Response) -> Any:
    """Decode a successful SuperDocs JSON response consistently."""
    try:
        return response.json()
    except ValueError as error:
        raise SuperDocsError("invalid provider JSON") from error


def superdocs_failure(error: SuperDocsError, failure_code: str):
    if str(error) == "SUPERDOCS_NOT_CONFIGURED":
        return failure(503, "SUPERDOCS_NOT_CONFIGURED")
    return failure(502, failure_code)
