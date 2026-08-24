"""The only module that talks to api.superdocs.app — every SuperDocs
interaction in this codebase funnels through it (design doc §10).

Scope for Milestone 1: the calls the brief calls the minimum contract
(upload, chat, approve, export) plus job polling, since edits run async.
Session lifecycle (init, focus, close), continue_prompt handling, and signed
download URLs are added when Milestone 3's drafting engine actually needs
them, not guessed at now.

No retry/backoff here — that's Milestone 6 (Hardening), scoped separately.
A failed call raises; the caller decides what bounded retry looks like.
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
            # Not a hang; a real ceiling still exists so nothing waits forever.
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
        # own 422 validation error, not the docs page this was originally
        # built from (which said `document_base64`; Task 1's own probe
        # script, written independently, guessed a third name,
        # `document_html`). The server's error is the more authoritative
        # source than either — see PROGRESS.md M1.
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
        """Async AI edit. `model_tier` (core/turbo/pro/max) and
        `thinking_depth` (fast/balanced/deep) are passed through when set;
        omitted entirely when None so the server's own defaults apply —
        the same call shape as before for callers that don't care."""
        body: dict[str, object] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }
        if model_tier is not None:
            body["model_tier"] = model_tier
        if thinking_depth is not None:
            body["thinking_depth"] = thinking_depth
        r = await self._client.post("/v1/chat/async", json=body)
        r.raise_for_status()
        return ChatAsyncResponse.model_validate(r.json())

    async def get_job(self, job_id: str) -> JobStatusResponse:
        r = await self._client.get(f"/v1/jobs/{job_id}")
        r.raise_for_status()
        return JobStatusResponse.model_validate(r.json())

    async def approve(
        self, *, session_id: str, job_id: str, approved: bool = True, chunk_id: str | None = None
    ) -> dict:
        # {job_id, approved} are the two fields the live API's 422 named as
        # required. chunk_id is not required by that same validation, but
        # omitting it left every real call returning batch_complete: false
        # with the document never actually updating — sent when known. See
        # PROGRESS.md M1 for the full trail.
        body: dict[str, object] = {"job_id": job_id, "approved": approved}
        if chunk_id is not None:
            body["chunk_id"] = chunk_id
        r = await self._client.post(f"/v1/chat/{session_id}/approve", json=body)
        r.raise_for_status()
        return r.json()

    async def approve_changes(
        self,
        *,
        session_id: str,
        job_id: str,
        approved: bool,
        changes: list[dict] | None = None,
        feedback: str | None = None,
    ) -> dict:
        """Decide AI-proposed changes (HITL gate). `changes` is a list of
        {change_id, approved?, feedback?}; the top-level `approved` is the
        default for entries that don't set their own (required by the API
        even in batch shape). Deny-with-feedback tells the AI to revise."""
        body: dict[str, object] = {"job_id": job_id, "approved": approved}
        if changes is not None:
            body["changes"] = changes
        if feedback is not None:
            body["feedback"] = feedback
        r = await self._client.post(f"/v1/chat/{session_id}/approve", json=body)
        r.raise_for_status()
        return r.json()

    async def get_session_documents(self, *, session_id: str) -> list[dict]:
        """Roster of documents open in a session. Carries the durable
        document id, which the structure-read endpoint needs."""
        r = await self._client.get(f"/v1/sessions/{session_id}/documents")
        r.raise_for_status()
        data = r.json()
        return data.get("documents", []) if isinstance(data, dict) else data

    async def get_document_detail(self, *, document_id: str) -> dict:
        """Free structure read: metadata + structure outline (headings with
        level/text/position, section_count, block_count, media). Used as the
        post-batch structural verification step — never billed."""
        r = await self._client.get(f"/v1/documents/{document_id}")
        r.raise_for_status()
        return r.json()

    async def revert_session(self, *, session_id: str, turn_index: int) -> dict:
        """Rewind the session (document + conversation) to before the given
        user-message turn. Returns document_state (HTML), compose_text,
        reverted_to_turn. Escape hatch for batch rollback — not the normal
        editing mechanism."""
        r = await self._client.post(
            f"/v1/sessions/{session_id}/revert", json={"turn_index": turn_index}
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
