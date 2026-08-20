"""The only module that talks to api.superdocs.app — every SuperDocs
interaction in classroom-app funnels through it.

Independently implemented for classroom-app, following the same wire
contract zoom-app established against the live API (upload, chat, approve,
export, job polling). The one difference from zoom-app's client: this one
adds `approve_batch`, the batch-approval request shape from the official
SuperDocs docs (`{changes: [{chunk_id, approved}]}`), which zoom-app never
tested against the live API.

No retry/backoff here — a failed call raises; the workflow layer decides
what bounded retry looks like.
"""

from __future__ import annotations

import base64
import json

import httpx

from app.superdocs.schemas import (
    ChatAsyncResponse,
    ExportResult,
    JobStatusResponse,
    UploadResponse,
)


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = "https://api.superdocs.app") -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            # Ops can take 30s-several minutes — the brief's own warning.
            timeout=httpx.Timeout(180.0, connect=15.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SuperDocsClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def upload_base64(
        self, *, file_base64: str, filename: str, session_id: str, return_html: bool = True
    ) -> UploadResponse:
        # The wire field is `file_base64` — confirmed against the live API's
        # own 422 validation error (the docs page said `document_base64`).
        r = await self._client.post(
            "/v1/documents/upload-base64",
            json={
                "file_base64": file_base64,
                "filename": filename,
                "session_id": session_id,
                "return_html": return_html,
            },
        )
        r.raise_for_status()
        return UploadResponse.model_validate(r.json())

    async def chat_async(
        self,
        *,
        message: str,
        session_id: str,
        approval_mode: str = "auto",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
    ) -> ChatAsyncResponse:
        payload: dict[str, object] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }
        if model_tier is not None:
            payload["model_tier"] = model_tier
        if thinking_depth is not None:
            payload["thinking_depth"] = thinking_depth
        r = await self._client.post(
            "/v1/chat/async",
            json=payload,
        )
        r.raise_for_status()
        return ChatAsyncResponse.model_validate(r.json())

    async def get_job(self, job_id: str) -> JobStatusResponse:
        r = await self._client.get(f"/v1/jobs/{job_id}")
        r.raise_for_status()
        return JobStatusResponse.model_validate(r.json())

    async def approve(
        self, *, session_id: str, job_id: str, approved: bool = True, chunk_id: str | None = None
    ) -> dict:
        """Individual approval — the shape zoom-app confirmed against the
        live API's 422: {job_id, approved} required, chunk_id optional."""
        body: dict[str, object] = {"job_id": job_id, "approved": approved}
        if chunk_id is not None:
            body["chunk_id"] = chunk_id
        r = await self._client.post(f"/v1/chat/{session_id}/approve", json=body)
        r.raise_for_status()
        return r.json()

    async def approve_batch(
        self, *, session_id: str, job_id: str, approved: bool, changes: list[dict]
    ) -> dict:
        """Approval with the CURRENT official SuperDocs schema
        (docs.superdocs.app/guides/integration-starter-prompt), live-
        verified 2026-08:

            {job_id, approved, changes: [{change_id, approved}]}

        The nested identifier is `change_id` — NOT `chunk_id`. Live testing
        proved this shape advances the job awaiting_approval -> completed
        (batch_complete: true), while the old chunk_id shapes never did.
        Per-change `approved` follows the teacher's decision; the docs
        state approved changes apply atomically and denied changes are
        discarded."""
        r = await self._client.post(
            f"/v1/chat/{session_id}/approve",
            json={"job_id": job_id, "approved": approved, "changes": changes},
        )
        r.raise_for_status()
        return r.json()

    async def export(self, *, session_id: str, format: str = "docx") -> ExportResult:
        r = await self._client.post(
            "/v1/documents/export", json={"session_id": session_id, "format": format}
        )
        r.raise_for_status()

        warnings: list[str] = []
        encoded = r.headers.get("x-export-warnings")
        if encoded:
            try:
                warnings = json.loads(base64.b64decode(encoded))
            except (ValueError, json.JSONDecodeError):
                pass  # a malformed warnings header shouldn't fail an otherwise-successful export

        return ExportResult(
            content=r.content,
            content_type=r.headers.get("content-type", "application/octet-stream"),
            warnings=warnings,
        )
