from __future__ import annotations

import base64
import json
import re
from typing import Any, Protocol

import httpx


class SuperDocsAPIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"SuperDocs {status_code} {code}: {message}")


class Transport(Protocol):
    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def get(self, path: str) -> dict[str, Any]: ...


def _error_from_response(response: httpx.Response) -> SuperDocsAPIError:
    try:
        body = response.json()
        detail = body.get("detail", body)
        if isinstance(detail, dict):
            code = str(detail.get("code", "error"))
            message = str(detail.get("message", detail))
        else:
            code = "error"
            message = str(detail)
    except Exception:
        code = "non_json_error"
        message = response.text[:300]
    return SuperDocsAPIError(response.status_code, code, message)


def _decode(response: httpx.Response) -> dict[str, Any]:
    """Return the body as a dict, whether the endpoint answered JSON or a raw file.

    Most endpoints answer JSON, but `/v1/documents/export` streams the .docx itself.
    Calling .json() on those bytes fails with a UTF-8 decode error somewhere inside the
    ZIP header -- an error that says nothing about what actually happened. Binary bodies
    are handed back under `content_bytes` so callers can treat both shapes uniformly.
    """
    content_type = response.headers.get("content-type", "")
    if "json" in content_type.lower():
        return response.json()

    # Every non-JSON body carries its bytes, including the text formats: `export`
    # documents docx, pdf, html, markdown and txt, and a markdown export is just as
    # much a file to be handed to someone as a .docx is.
    body: dict[str, Any] = {
        "content_bytes": response.content,
        "filename": _filename_from_disposition(
            response.headers.get("content-disposition", "")
        ),
    }
    if content_type.startswith(("text/", "application/xml")):
        body["text"] = response.text
    warnings = _export_warnings(response.headers.get("x-export-warnings", ""))
    if warnings:
        body["warnings"] = warnings
    return body


def _export_warnings(header: str) -> Any:
    """Decode the base64 JSON of non-fatal export problems, if the server sent any.

    Dropping these would let an export report success while quietly knowing something
    was lost. A malformed header is itself not worth failing an otherwise good export,
    so it degrades to None rather than raising.
    """
    if not header:
        return None
    try:
        return json.loads(base64.b64decode(header))
    except Exception:  # noqa: BLE001 - a warning must never break the thing it warns about
        return None


def _filename_from_disposition(disposition: str) -> str | None:
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition)
    return match.group(1) if match else None


class HTTPTransport:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def _client_instance(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._client_instance()
        response = await client.post(
            f"{self._base_url}{path}", json=payload, headers=self._headers()
        )
        if response.status_code >= 400:
            raise _error_from_response(response)
        return _decode(response)

    async def get(self, path: str) -> dict[str, Any]:
        client = await self._client_instance()
        response = await client.get(f"{self._base_url}{path}", headers=self._headers())
        if response.status_code >= 400:
            raise _error_from_response(response)
        return _decode(response)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
