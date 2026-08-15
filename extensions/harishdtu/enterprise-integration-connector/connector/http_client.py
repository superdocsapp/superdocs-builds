"""
The one place every SuperDocs HTTP call goes through. Owns:
  - Authorization header injection (never logged)
  - Status-code -> typed error mapping (errors.py)
  - The retry contract: retry 429/500/504, honor Retry-After exactly when
    present, exponential backoff + jitter otherwise, never retry
    400/401/403/404/410/415/422, and 413 is surfaced as a payload-size problem
    rather than retried.
  - Never logging Authorization headers or full document content
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from connector.config import ConnectorConfig
from connector.errors import (
    STATUS_CODE_MAP,
    RateLimitError,
    ServerError,
    SuperDocsConnectorError,
    UnknownSuperDocsError,
)
from connector.errors import (
    TimeoutError as SDTimeoutError,
)

logger = logging.getLogger("superdocs_connector.http")

# Status codes the retry loop will act on at all. Anything else is either a
# terminal success or a terminal typed error raised immediately (no retry).
RETRYABLE_STATUS_CODES = frozenset({429, 500, 504})

# Fields that must never appear in a log line, even at DEBUG.
_SENSITIVE_HEADER_NAMES = frozenset({"authorization"})


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        k: ("***redacted***" if k.lower() in _SENSITIVE_HEADER_NAMES else v)
        for k, v in headers.items()
    }


def _extract_detail(response: httpx.Response) -> str:
    """
    SuperDocs error bodies are normally {"detail": "..."}. Infrastructure-layer
    429s are plain text ('Rate exceeded') with no JSON body at all — treat that
    as a distinct, expected shape rather than a parse failure.
    """
    try:
        payload = response.json()
        if isinstance(payload, dict) and "detail" in payload:
            return str(payload["detail"])
        return str(payload)
    except ValueError:
        return response.text[:500] if response.text else f"HTTP {response.status_code}"


def _retry_after_seconds(response: httpx.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None  # malformed header -> treat as absent, fall back to backoff+jitter


def map_error(response: httpx.Response) -> SuperDocsConnectorError:
    """Central status-code -> typed-error mapping. The only place STATUS_CODE_MAP is read."""
    detail = _extract_detail(response)
    retry_after = _retry_after_seconds(response)
    error_cls = STATUS_CODE_MAP.get(response.status_code, UnknownSuperDocsError)
    return error_cls(
        f"SuperDocs API returned {response.status_code}: {detail}",
        status_code=response.status_code,
        detail=detail,
        retry_after_seconds=retry_after,
    )


class SuperDocsHTTPClient:
    """
    Thin async wrapper around httpx with the retry/error contract baked in.
    One instance per connector invocation is fine; it's cheap to construct.
    """

    def __init__(self, config: ConnectorConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            transport=transport,  # injected in tests; real usage lets httpx pick the default
        )
        # A second, deliberately unscoped (no base_url, no auth) client for
        # pre-signed cloud-storage PUTs (see put_presigned below) -- shares
        # the same injected transport so tests can mock both without a real
        # network call, but never carries the SuperDocs Authorization header.
        self._raw_client = httpx.AsyncClient(timeout=config.timeout_seconds, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._raw_client.aclose()

    async def __aenter__(self) -> SuperDocsHTTPClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    def _headers(self, *, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """
        Issues one logical request, retrying per the documented contract.
        Returns the successful httpx.Response (2xx) or raises a typed
        SuperDocsConnectorError subclass on a terminal (non-retried, or
        retries-exhausted) failure.
        """
        headers = self._headers()
        attempt = 0
        last_error: SuperDocsConnectorError | None = None

        while attempt <= self._config.max_retries:
            attempt += 1
            logger.debug(
                "SuperDocs request attempt=%d method=%s path=%s headers=%s",
                attempt, method, path, _redact_headers(headers),
            )
            try:
                response = await self._client.request(method, path, json=json, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                # A network-level timeout (connect/read), distinct from SuperDocs'
                # own 504. Treated the same as a retryable server-side timeout.
                last_error = SDTimeoutError(
                    f"Network timeout calling SuperDocs {method} {path}: {exc}",
                    status_code=None, detail=str(exc),
                )
                await self._backoff(attempt, last_error)
                continue

            if 200 <= response.status_code < 300:
                return response

            error = map_error(response)

            if response.status_code not in RETRYABLE_STATUS_CODES:
                # 400/401/403/404/409/410/413/415/422 and anything unmapped:
                # fail immediately, no retry loop.
                raise error

            last_error = error
            if attempt > self._config.max_retries:
                break
            await self._backoff(attempt, error)

        assert last_error is not None
        raise last_error

    async def _backoff(self, attempt: int, error: SuperDocsConnectorError) -> None:
        if isinstance(error, RateLimitError) and error.retry_after_seconds is not None:
            # Application 429 with a Retry-After header: honor it exactly, no jitter.
            delay = error.retry_after_seconds
            logger.info("Rate limited; honoring Retry-After=%.1fs (attempt %d)", delay, attempt)
        else:
            # Infra 429 (no Retry-After), 500, or network timeout: exponential
            # backoff with full jitter, capped so a flaky run doesn't stall forever.
            base = min(2 ** (attempt - 1), 30)
            delay = random.uniform(0, base)
            logger.info(
                "Retrying after backoff=%.2fs (attempt %d, %s)",
                delay, attempt, error.__class__.__name__,
            )
        await asyncio.sleep(delay)

    async def post_multipart(self, path: str, *, files: dict[str, tuple[str, bytes, str]], data: dict[str, Any] | None = None) -> dict[str, Any]:
        """multipart/form-data POST (used for POST /v1/documents/upload). No
        Content-Type override -- httpx sets the multipart boundary itself."""
        response = await self._request_multipart(path, files=files, data=data)
        return response.json()

    async def _request_multipart(self, path: str, *, files: dict, data: dict | None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._config.api_key}"}  # no Content-Type: httpx sets multipart boundary
        attempt = 0
        last_error: SuperDocsConnectorError | None = None
        while attempt <= self._config.max_retries:
            attempt += 1
            try:
                response = await self._client.request(
                    "POST", path, files=files, data=data or {}, headers=headers
                )
            except httpx.TimeoutException as exc:
                last_error = SDTimeoutError(
                    f"Network timeout calling SuperDocs POST {path}: {exc}", status_code=None, detail=str(exc)
                )
                await self._backoff(attempt, last_error)
                continue
            if 200 <= response.status_code < 300:
                return response
            error = map_error(response)
            if response.status_code not in RETRYABLE_STATUS_CODES:
                raise error
            last_error = error
            if attempt > self._config.max_retries:
                break
            await self._backoff(attempt, error)
        assert last_error is not None
        raise last_error

    async def put_presigned(self, url: str, content: bytes, *, content_type: str) -> None:
        """
        PUTs raw bytes directly to a pre-signed cloud-storage URL returned by
        POST /v1/uploads. Deliberately bypasses this client's normal
        Authorization-header injection: the SuperDocs API key must never be
        sent to a third-party storage endpoint, and the pre-signed URL itself
        already carries its own signed authorization. Uses self._raw_client
        (base_url-less, unauthenticated, but sharing this instance's injected
        transport so tests can mock it too) with a small bounded retry for
        transient network failures only -- a bad/expired pre-signed URL
        (403/404) is not retried.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._raw_client.put(url, content=content, headers={"Content-Type": content_type})
            except httpx.TimeoutException as exc:
                if attempt > self._config.max_retries:
                    raise SDTimeoutError(
                        f"Network timeout PUTting to pre-signed upload URL: {exc}",
                        status_code=None, detail=str(exc),
                    )
                await self._backoff(attempt, SDTimeoutError("presigned PUT timeout", status_code=None))
                continue
            if 200 <= response.status_code < 300:
                return
            if response.status_code >= 500 and attempt <= self._config.max_retries:
                await self._backoff(attempt, ServerError(
                    f"Pre-signed upload PUT returned {response.status_code}", status_code=response.status_code,
                ))
                continue
            raise ServerError(
                f"Pre-signed upload PUT failed with {response.status_code} "
                f"(pre-signed URLs expire after 5 minutes -- if this is a 403, the URL may have expired)",
                status_code=response.status_code, detail=response.text[:300],
            )

    # -- convenience wrappers used by the operations layer --

    async def post_json(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        response = await self.request("POST", path, json=json)
        return response.json()

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self.request("GET", path, params=params)
        return response.json()

    async def post_binary(self, path: str, json: dict[str, Any]) -> httpx.Response:
        """For endpoints that return a binary body (export) rather than JSON."""
        return await self.request("POST", path, json=json)
