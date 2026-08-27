from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Self

import httpx

from .config import Settings


class SuperDocsError(RuntimeError):
    pass


@dataclass(frozen=True)
class SuperDocsOutcome:
    updated_html: str
    response_text: str
    proposed_changes: list[dict[str, Any]] = field(default_factory=list)
    operations_charged: int | None = None
    raw_usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UploadedDocument:
    html: str
    filename: str
    chunks_count: int | None = None


@dataclass(frozen=True)
class ExportedDocument:
    content: bytes
    content_type: str
    warnings: str | None = None


def _nested(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _first(data: dict[str, Any], paths: list[tuple[str, ...]]) -> Any:
    for path in paths:
        value = _nested(data, *path)
        if value is not None:
            return value
    return None


def _usage(data: dict[str, Any]) -> dict[str, Any]:
    value = _first(
        data,
        [
            ("usage",),
            ("result", "usage"),
            ("metadata", "usage"),
            ("metadata", "result", "usage"),
        ],
    )
    return value if isinstance(value, dict) else {}


def _operations_charged(data: dict[str, Any]) -> int | None:
    usage = _usage(data)
    value = usage.get("ops_charged")
    if isinstance(value, int):
        return value
    return None


def _response_text(data: dict[str, Any]) -> str:
    value = _first(
        data,
        [
            ("response",),
            ("result", "response"),
            ("result", "message"),
            ("metadata", "result", "response"),
        ],
    )
    return value if isinstance(value, str) else ""


def _updated_html(data: dict[str, Any]) -> str | None:
    value = _first(
        data,
        [
            ("document_changes", "updated_html"),
            ("result", "document_changes", "updated_html"),
            ("result", "updated_html"),
            ("metadata", "result", "document_changes", "updated_html"),
            ("metadata", "final_result", "document_changes", "updated_html"),
            ("metadata", "updated_html"),
        ],
    )
    return value if isinstance(value, str) and value.strip() else None


def _pending_changes(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = _first(
        data,
        [
            ("metadata", "pending_changes"),
            ("pending_changes",),
            ("result", "pending_changes"),
        ],
    )
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SuperDocsError("Pending-change content was not valid JSON") from exc
    if isinstance(value, dict):
        value = value.get("changes", [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


class SuperDocsClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
            },
            timeout=settings.request_timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, json=json_body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise SuperDocsError(
                f"SuperDocs returned HTTP {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SuperDocsError(f"SuperDocs request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise SuperDocsError("SuperDocs returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise SuperDocsError("SuperDocs returned an unexpected response shape")
        return payload

    async def analyze(
        self, *, document_html: str | None, message: str, session_id: str
    ) -> SuperDocsOutcome:
        body = {
            "message": message,
            "session_id": session_id,
            "approval_mode": "approve_all",
        }
        if document_html is not None:
            body["document_html"] = document_html
        payload = await self._request(
            "POST",
            "/v1/chat",
            json_body=body,
        )
        return SuperDocsOutcome(
            updated_html=_updated_html(payload) or document_html or "",
            response_text=_response_text(payload),
            operations_charged=_operations_charged(payload),
            raw_usage=_usage(payload),
        )

    async def edit_with_approval(
        self,
        *,
        document_html: str | None,
        message: str,
        session_id: str,
    ) -> SuperDocsOutcome:
        body = {
            "message": message,
            "session_id": session_id,
            "approval_mode": "ask_every_time",
        }
        if document_html is not None:
            body["document_html"] = document_html
        started = await self._request(
            "POST",
            "/v1/chat/async",
            json_body=body,
        )
        job_id = started.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise SuperDocsError("Async chat response did not include job_id")

        deadline = time.monotonic() + self.settings.job_timeout_seconds
        proposed_changes: list[dict[str, Any]] = []
        approved_batches: set[tuple[str, ...]] = set()
        latest = started
        while time.monotonic() < deadline:
            latest = await self._request("GET", f"/v1/jobs/{job_id}")
            status = latest.get("status")
            if status == "awaiting_approval":
                pending = _pending_changes(latest)
                decisions = [
                    {"change_id": item["change_id"], "approved": True}
                    for item in pending
                    if isinstance(item.get("change_id"), str)
                ]
                batch_key = tuple(sorted(item["change_id"] for item in decisions))
                if batch_key in approved_batches:
                    await asyncio.sleep(self.settings.poll_interval_seconds)
                    continue
                approved_batches.add(batch_key)
                proposed_changes.extend(pending)
                approval: dict[str, Any] = {"job_id": job_id, "approved": True}
                if decisions:
                    approval["changes"] = decisions
                await self._request(
                    "POST",
                    f"/v1/chat/{session_id}/approve",
                    json_body=approval,
                )
            elif status == "completed":
                updated = _updated_html(latest)
                if updated is None:
                    raise SuperDocsError("Completed edit did not include updated document HTML")
                return SuperDocsOutcome(
                    updated_html=updated,
                    response_text=_response_text(latest),
                    proposed_changes=proposed_changes,
                    operations_charged=_operations_charged(latest),
                    raw_usage=_usage(latest),
                )
            elif status in {"failed", "cancelled"}:
                detail = latest.get("error") or _nested(latest, "metadata", "error") or status
                raise SuperDocsError(f"SuperDocs job {status}: {detail}")
            await asyncio.sleep(self.settings.poll_interval_seconds)

        raise SuperDocsError(
            f"SuperDocs job did not finish within {self.settings.job_timeout_seconds:g} seconds"
        )

    async def upload_document(
        self, *, filename: str, content: bytes, session_id: str
    ) -> UploadedDocument:
        try:
            response = await self._client.post(
                "/v1/documents/upload",
                files={"file": (filename, content, "text/html")},
                data={"session_id": session_id},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise SuperDocsError(
                f"SuperDocs upload returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SuperDocsError(f"SuperDocs upload failed: {exc}") from exc
        html = payload.get("html") if isinstance(payload, dict) else None
        if not isinstance(html, str) or not html.strip():
            raise SuperDocsError("SuperDocs upload did not return parsed document HTML")
        chunks_count = payload.get("chunks_count")
        return UploadedDocument(
            html=html,
            filename=str(payload.get("filename") or filename),
            chunks_count=chunks_count if isinstance(chunks_count, int) else None,
        )

    async def export_document(
        self, *, session_id: str, filename: str, format: str = "html"
    ) -> ExportedDocument:
        try:
            response = await self._client.post(
                "/v1/documents/export",
                json={
                    "session_id": session_id,
                    "format": format,
                    "options": {"filename": filename},
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SuperDocsError(
                f"SuperDocs export returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SuperDocsError(f"SuperDocs export failed: {exc}") from exc
        if not response.content:
            raise SuperDocsError("SuperDocs export returned an empty file")
        return ExportedDocument(
            content=response.content,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            warnings=response.headers.get("x-export-warnings"),
        )
