from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from .errors import (
    SuperDocsError,
    SuperDocsTimeoutError,
    TransportError,
    error_from_response,
)

DEFAULT_BASE_URL = "https://api.superdocs.app"


@dataclass
class Response:
    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


class SyncTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        files: Any | None = None,
        data: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response: ...

    def stream_lines(
        self, path: str, *, headers: dict[str, str] | None = None, timeout: float | None = None
    ) -> Iterator[str]: ...

    def put_bytes(
        self, url: str, content: bytes, *, headers: dict[str, str], timeout: float | None = None
    ) -> Response: ...


class AsyncTransport(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        files: Any | None = None,
        data: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response: ...

    def stream_lines(
        self, path: str, *, headers: dict[str, str] | None = None, timeout: float | None = None
    ) -> AsyncIterator[str]: ...

    async def put_bytes(
        self, url: str, content: bytes, *, headers: dict[str, str], timeout: float | None = None
    ) -> Response: ...


class HttpxSyncTransport:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        import httpx

        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        files: Any | None = None,
        data: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response:
        try:
            response = self.client.request(
                method,
                path,
                json=json_body,
                files=files,
                data=data,
                content=content,
                headers=headers,
                timeout=timeout,
            )
        except Exception as exc:
            raise _transport_exception(exc) from exc
        return Response(response.status_code, dict(response.headers), response.content)

    def stream_lines(
        self, path: str, *, headers: dict[str, str] | None = None, timeout: float | None = None
    ) -> Iterator[str]:
        try:
            with self.client.stream("GET", path, headers=headers, timeout=timeout) as response:
                if response.status_code >= 400:
                    body = response.read()
                    wrapped = Response(response.status_code, dict(response.headers), body)
                    raise error_from_response(response.status_code, wrapped.headers, safe_json(wrapped))
                yield from response.iter_lines()
        except SuperDocsError:
            raise
        except Exception as exc:
            raise _transport_exception(exc) from exc

    def put_bytes(
        self, url: str, content: bytes, *, headers: dict[str, str], timeout: float | None = None
    ) -> Response:
        import httpx

        try:
            response = httpx.put(url, content=content, headers=headers, timeout=timeout)
        except Exception as exc:
            raise _transport_exception(exc) from exc
        return Response(response.status_code, dict(response.headers), response.content)

    def close(self) -> None:
        self.client.close()

    def __repr__(self) -> str:
        return "HttpxSyncTransport(api_key='***')"


class HttpxAsyncTransport:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        import httpx

        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=base_url, headers={"Authorization": f"Bearer {api_key}"}
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        files: Any | None = None,
        data: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response:
        try:
            response = await self.client.request(
                method,
                path,
                json=json_body,
                files=files,
                data=data,
                content=content,
                headers=headers,
                timeout=timeout,
            )
        except Exception as exc:
            raise _transport_exception(exc) from exc
        return Response(response.status_code, dict(response.headers), response.content)

    async def stream_lines(
        self, path: str, *, headers: dict[str, str] | None = None, timeout: float | None = None
    ) -> AsyncIterator[str]:
        try:
            async with self.client.stream("GET", path, headers=headers, timeout=timeout) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    wrapped = Response(response.status_code, dict(response.headers), body)
                    raise error_from_response(response.status_code, wrapped.headers, safe_json(wrapped))
                async for line in response.aiter_lines():
                    yield line
        except SuperDocsError:
            raise
        except Exception as exc:
            raise _transport_exception(exc) from exc

    async def put_bytes(
        self, url: str, content: bytes, *, headers: dict[str, str], timeout: float | None = None
    ) -> Response:
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                response = await client.put(url, content=content, headers=headers, timeout=timeout)
        except Exception as exc:
            raise _transport_exception(exc) from exc
        return Response(response.status_code, dict(response.headers), response.content)

    async def close(self) -> None:
        await self.client.aclose()

    def __repr__(self) -> str:
        return "HttpxAsyncTransport(api_key='***')"


def _transport_exception(exc: Exception) -> TransportError:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return SuperDocsTimeoutError(
            "SuperDocs request timed out.",
            code="transport_timeout",
            retryable=True,
            suggested_action="Retry with the same idempotency key or increase the per-call timeout.",
        )
    return TransportError(
        f"SuperDocs transport failed: {exc}",
        code="transport_error",
        retryable=True,
        suggested_action="Check network connectivity and retry with the same idempotency key.",
    )


def api_key_from_env() -> str:
    key = os.getenv("SUPERDOCS_API_KEY")
    if not key:
        raise SuperDocsError(
            "Missing SUPERDOCS_API_KEY",
            code="missing_api_key",
            suggested_action="Set SUPERDOCS_API_KEY in the server environment.",
        )
    return key


def _delay(response: Response, attempt: int) -> float:
    raw = response.headers.get("retry-after") or response.headers.get("Retry-After")
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    exponential_delay: float = 0.25 * (2.0**attempt)
    return min(8.0, exponential_delay)


def request_with_retries(
    transport: SyncTransport,
    method: str,
    path: str,
    *,
    json_body: Any | None = None,
    files: Any | None = None,
    data: Any | None = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    retries: int = 2,
) -> Response:
    for attempt in range(retries + 1):
        response = transport.request(
            method,
            path,
            json_body=json_body,
            files=files,
            data=data,
            content=content,
            headers=headers,
            timeout=timeout,
        )
        if response.status_code < 400:
            return response
        error = error_from_response(response.status_code, response.headers, safe_json(response))
        if not error.retryable or attempt >= retries:
            raise error
        time.sleep(_delay(response, attempt))
    raise AssertionError("unreachable")


async def async_request_with_retries(
    transport: AsyncTransport,
    method: str,
    path: str,
    *,
    json_body: Any | None = None,
    files: Any | None = None,
    data: Any | None = None,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    retries: int = 2,
) -> Response:
    for attempt in range(retries + 1):
        response = await transport.request(
            method,
            path,
            json_body=json_body,
            files=files,
            data=data,
            content=content,
            headers=headers,
            timeout=timeout,
        )
        if response.status_code < 400:
            return response
        error = error_from_response(response.status_code, response.headers, safe_json(response))
        if not error.retryable or attempt >= retries:
            raise error
        await asyncio.sleep(_delay(response, attempt))
    raise AssertionError("unreachable")


def ensure_success(response: Response) -> Response:
    if response.status_code >= 400:
        raise error_from_response(response.status_code, response.headers, safe_json(response))
    return response


def safe_json(response: Response) -> Any:
    try:
        return response.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return response.body.decode("utf-8", errors="replace")


def with_query(path: str, **params: Any) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    return path if not clean else f"{path}?{urlencode(clean)}"


def iter_sse_lines(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    event_type = "message"
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            if data_lines:
                yield _decode_sse(event_type, data_lines)
            event_type, data_lines = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event_type = line[6:].lstrip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield _decode_sse(event_type, data_lines)


def _decode_sse(event_type: str, data_lines: list[str]) -> dict[str, Any]:
    data = json.loads("\n".join(data_lines))
    if not isinstance(data, dict):
        data = {"content": data}
    data.setdefault("type", event_type)
    return data


async def async_iter_sse_lines(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    event_type = "message"
    data_lines: list[str] = []
    async for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            if data_lines:
                yield _decode_sse(event_type, data_lines)
            event_type, data_lines = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event_type = line[6:].lstrip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield _decode_sse(event_type, data_lines)
