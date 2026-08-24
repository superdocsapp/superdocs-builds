"""Thin async HTTP client for the SuperDocs REST API.

Endpoint paths and payloads are aligned with the live OpenAPI specification.

Design decisions:
- Utilizes a single injected `httpx.AsyncClient` to facilitate dependency 
  injection of mocked clients during test execution without network access.
- The `parse_changes()` method implements double-parsing to handle cases where 
  the upstream API returns `pending_changes` as a JSON-encoded string.
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import httpx

from app.integrations.superdocs.exceptions import (
    SuperDocsAPIError,
    SuperDocsTimeoutError,
)
from app.integrations.superdocs.schemas import (
    ExportResult,
    JobResult,
    UploadResult,
)

# --- Endpoint map (matches live OpenAPI operationId paths) ---
_UPLOAD_PATH = "/v1/documents/upload"
_CHAT_ASYNC_PATH = "/v1/chat/async"
_JOB_PATH = "/v1/jobs/{job_id}"
_APPROVE_PATH = "/v1/chat/{session_id}/approve"
_EXPORT_PATH = "/v1/documents/export"

# Our gateway accepts "md"; SuperDocs ExportRequest enum uses "markdown".
_EXPORT_FORMAT = {
    "docx": "docx",
    "pdf": "pdf",
    "html": "html",
    "txt": "txt",
    "md": "markdown",
    "markdown": "markdown",
    "doc": "doc",
}


class SuperDocsClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._client = client

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        client = await self._http()
        try:
            response = await client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise SuperDocsTimeoutError(str(exc)) from exc
        if response.status_code >= 400:
            detail = _safe_json(response) or {"message": response.text[:500]}
            raise SuperDocsAPIError(
                response.status_code,
                detail.get("message", detail.get("detail", "request failed")),
                detail,
            )
        return _safe_json(response) or {}

    # --- The four-call contract ---

    async def upload_document(
        self,
        *,
        file_path: str,
        filename: str,
        content_type: str,
        session_id: str | None = None,
    ) -> UploadResult:
        """POST /v1/documents/upload — multipart file + session_id form field.

        Query ?index=true triggers immediate AI indexing (recommended for API
        clients per OpenAPI). The route handler already streamed the upload to
        disk; here we stream the file to SuperDocs without buffering in memory.
        """
        client = await self._http()
        sid = session_id or uuid.uuid4().hex
        with open(file_path, "rb") as fh:
            files = {"file": (filename, fh, content_type)}
            data = {"session_id": sid, "open_mode": "replace"}
            try:
                response = await client.post(
                    _UPLOAD_PATH,
                    files=files,
                    data=data,
                    params={"index": "true"},
                )
            except httpx.TimeoutException as exc:
                raise SuperDocsTimeoutError(str(exc)) from exc
        if response.status_code >= 400:
            detail = _safe_json(response) or {"message": response.text[:500]}
            raise SuperDocsAPIError(
                response.status_code,
                detail.get("message", detail.get("detail", "upload failed")),
                detail,
            )
        payload = _safe_json(response) or {}
        return _parse_upload_response(payload, fallback_session_id=sid)

    async def start_chat_async(
        self,
        *,
        session_id: str,
        instruction: str,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        response_mode: str = "full",
    ) -> JobResult:
        """POST /v1/chat/async — AsyncChatRequest (session_id + message only).

        The document is already loaded in the session from upload; there is no
        document_id field on AsyncChatRequest.
        """
        payload: dict[str, Any] = {
            "session_id": session_id,
            "message": instruction,
            "approval_mode": approval_mode,
            "async_mode": True,
            "response_mode": response_mode,
        }
        if model_tier:
            payload["model_tier"] = model_tier
        data = await self._request("POST", _CHAT_ASYNC_PATH, json=payload)
        return self._to_job_result(data)

    async def get_job(self, job_id: str) -> JobResult:
        """GET /v1/jobs/{job_id} — returns JobResponse."""
        data = await self._request("GET", _JOB_PATH.format(job_id=job_id))
        return self._to_job_result(data)

    async def decide_change(
        self,
        *,
        session_id: str,
        job_id: str,
        change_id: str,
        approved: bool,
        feedback: str | None = None,
    ) -> JobResult:
        """POST /v1/chat/{session_id}/approve — ApprovalRequest (one change).

        Uses change_id (PendingChange.change_id from metadata.pending_changes),
        not a separate /jobs/.../approvals route.
        """
        payload: dict[str, Any] = {
            "job_id": job_id,
            "change_id": change_id,
            "approved": approved,
        }
        if feedback is not None:
            payload["feedback"] = feedback
        data = await self._request(
            "POST", _APPROVE_PATH.format(session_id=session_id), json=payload
        )
        return self._to_job_result(data)

    async def export_document(self, *, session_id: str, fmt: str = "docx") -> ExportResult:
        """POST /v1/documents/export — ExportRequest (session_id + format).

        SuperDocs may return JSON (download_url envelope), plain text (txt/md/html),
        or raw binary (docx/pdf). We normalize all three into ExportResult.
        """
        export_format = _EXPORT_FORMAT.get(fmt.lower(), fmt.lower())
        payload = {"session_id": session_id, "format": export_format}
        client = await self._http()
        try:
            response = await client.post(_EXPORT_PATH, json=payload)
        except httpx.TimeoutException as exc:
            raise SuperDocsTimeoutError(str(exc)) from exc
        if response.status_code >= 400:
            detail = _safe_json(response) or {"message": response.text[:500]}
            raise SuperDocsAPIError(
                response.status_code,
                detail.get("message", detail.get("detail", "export failed")),
                detail,
            )
        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type == "application/json" or response.text.startswith("{"):
            data = _safe_json(response) or {}
            return _parse_export_response(data)
        if content_type.startswith("text/") or export_format in {"txt", "markdown", "html"}:
            return ExportResult(inline_content=response.text, ops_cost=0.0)
        # Binary formats (docx/pdf/doc): return base64 so our gateway can relay it.
        encoded = base64.b64encode(response.content).decode("ascii")
        return ExportResult(content_base64=encoded, ops_cost=0.0)

    # --- Parsing helpers ---

    def _to_job_result(self, data: dict[str, Any]) -> JobResult:
        metadata = data.get("metadata") or {}
        result = data.get("result") or {}
        doc_changes = result.get("document_changes") or {}
        usage = result.get("usage") or {}

        pending = metadata.get("pending_changes") or doc_changes.get("pending_changes")
        document_html = data.get("document_html") or doc_changes.get("updated_html")
        ops = usage.get("ops_charged", data.get("ops_cost", metadata.get("ops_cost", 0.0)))

        return JobResult(
            job_id=str(data.get("job_id") or data.get("id") or ""),
            status=str(data.get("status") or "pending"),
            session_id=str(data.get("session_id") or ""),
            document_html=document_html,
            pending_changes=self.parse_changes(pending),
            ops_cost=float(ops or 0.0),
            raw=data,
        )

    @staticmethod
    def parse_changes(pending: Any) -> list[dict]:
        """DOUBLE-PARSE proposed changes when they arrive as a JSON string."""
        if pending is None:
            return []
        if isinstance(pending, str):
            try:
                pending = json.loads(pending)
            except json.JSONDecodeError:
                return []
        if isinstance(pending, dict) and "changes" in pending:
            pending = pending["changes"]
            if isinstance(pending, str):
                try:
                    pending = json.loads(pending)
                except json.JSONDecodeError:
                    return []
        if isinstance(pending, list):
            return [c for c in pending if isinstance(c, dict)]
        return []


def _parse_upload_response(data: dict[str, Any], *, fallback_session_id: str) -> UploadResult:
    """Best-effort upload response parsing (OpenAPI schema is underspecified)."""
    session_id = str(data.get("session_id") or fallback_session_id)
    document_id = data.get("document_id") or data.get("focused_document_id") or data.get("id")
    documents = data.get("documents")
    if not document_id and isinstance(documents, list) and documents:
        first = documents[0]
        if isinstance(first, dict):
            document_id = first.get("id") or first.get("document_id")
    # Session-only uploads are valid; use session_id as a stable fallback id.
    if not document_id:
        document_id = session_id
    usage = data.get("usage") or {}
    ops = usage.get("ops_charged", data.get("ops_cost", 0.0))
    return UploadResult(
        document_id=str(document_id),
        session_id=session_id,
        ops_cost=float(ops or 0.0),
    )


def _parse_export_response(data: dict[str, Any]) -> ExportResult:
    download_url = data.get("download_url") or data.get("url")
    content_base64 = data.get("content_base64") or data.get("base64")
    inline = data.get("content") or data.get("html") or data.get("markdown") or data.get("text")
    usage = data.get("usage") or {}
    ops = usage.get("ops_charged", data.get("ops_cost", 0.0))
    return ExportResult(
        download_url=download_url,
        content_base64=content_base64,
        inline_content=str(inline) if inline else None,
        ops_cost=float(ops or 0.0),
    )


def _safe_json(response: httpx.Response) -> dict | None:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}
    except (ValueError, json.JSONDecodeError):
        return None
