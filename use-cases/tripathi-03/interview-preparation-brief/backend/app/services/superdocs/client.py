"""SuperDocs REST client — upload, chat, approve, export (Task 2 contract)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, LLMConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_POLISH_INSTRUCTION = (
    "Format this as a professional Interview Preparation Brief. "
    "Improve headings, spacing, and readability for a job seeker. "
    "Do NOT invent employers, metrics, skills, or experience. "
    "Preserve every 'No evidence found.' string exactly. "
    "Keep all factual resume/JD/company content unchanged except for light formatting."
)


def normalize_pending_changes(raw: Any) -> list[dict[str, Any]]:
    """
    SuperDocs tip: proposed-change content may arrive as a JSON-encoded string
    and needs a second parse. Missing that yields empty/undefined diff cards.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Could not JSON-decode pending_changes string")
            return []
    if isinstance(raw, dict):
        # Sometimes wrapped as {"changes": [...]}
        raw = raw.get("changes") or raw.get("pending_changes") or [raw]
    if not isinstance(raw, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                continue
        if not isinstance(item, dict):
            continue
        # Nested content fields may also be double-encoded
        for key in ("content", "proposed_content", "new_html", "old_html", "diff"):
            value = item.get(key)
            if isinstance(value, str) and value[:1] in {"{", "["}:
                try:
                    item[key] = json.loads(value)
                except json.JSONDecodeError:
                    pass
        normalized.append(item)
    return normalized


class SuperDocsClient:
    """Minimal SuperDocs API wrapper for the four required calls."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.superdocs_api_key.strip():
            raise LLMConfigurationError(
                "SUPERDOCS_API_KEY is required. Create one at use.superdocs.app → Settings → API Keys."
            )
        self.base_url = self.settings.superdocs_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {self.settings.superdocs_api_key.strip()}",
        }

    def _raise_for_status(self, response: httpx.Response, action: str) -> None:
        if response.is_success:
            return
        detail = response.text[:800]
        try:
            payload = response.json()
            detail = str(payload.get("detail") or payload.get("error") or payload)[:800]
        except Exception:  # noqa: BLE001
            pass
        raise AppError(f"SuperDocs {action} failed ({response.status_code}): {detail}")

    async def upload_document(
        self,
        *,
        session_id: str,
        filename: str,
        content: bytes,
        content_type: str = "text/html",
    ) -> dict[str, Any]:
        """1) Upload a document into a SuperDocs session."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/documents/upload",
                headers=self._headers,
                files={"file": (filename, content, content_type)},
                data={"session_id": session_id},
            )
        self._raise_for_status(response, "upload")
        data = response.json()
        logger.info(
            "SuperDocs upload session=%s filename=%s chunks=%s",
            session_id,
            data.get("filename") or filename,
            data.get("chunks_count"),
        )
        return data

    async def chat_async(
        self,
        *,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
    ) -> dict[str, Any]:
        """2) Send an edit instruction (async — required for HITL approve)."""
        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "model_tier": model_tier,
        }
        if document_html is not None:
            body["document_html"] = document_html

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/async",
                headers={**self._headers, "Content-Type": "application/json"},
                json=body,
            )
        self._raise_for_status(response, "chat/async")
        data = response.json()
        logger.info("SuperDocs chat_async session=%s job=%s", session_id, data.get("job_id"))
        return data

    async def get_job(self, job_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{self.base_url}/v1/jobs/{job_id}",
                headers=self._headers,
            )
        self._raise_for_status(response, "get_job")
        data = response.json()
        metadata = data.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
            data["metadata"] = metadata
        pending = metadata.get("pending_changes") if isinstance(metadata, dict) else None
        if pending is None and isinstance(data.get("pending_changes"), (list, str, dict)):
            pending = data.get("pending_changes")
        data["pending_changes"] = normalize_pending_changes(pending)
        return data

    async def approve(
        self,
        *,
        session_id: str,
        job_id: str,
        approved: bool,
        changes: list[dict[str, Any]] | None = None,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """3) Approve or reject proposed changes (HITL gate)."""
        body: dict[str, Any] = {
            "job_id": job_id,
            "approved": approved,
        }
        if changes is not None:
            body["changes"] = changes
        if feedback:
            body["feedback"] = feedback

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/{session_id}/approve",
                headers={**self._headers, "Content-Type": "application/json"},
                json=body,
            )
        self._raise_for_status(response, "approve")
        try:
            return response.json()
        except Exception:  # noqa: BLE001
            return {"status": "ok", "raw": response.text[:500]}

    async def export(
        self,
        *,
        session_id: str,
        format: str = "docx",
        filename: str | None = None,
    ) -> tuple[bytes, str]:
        """4) Export the finished document (exports do not cost operations)."""
        body: dict[str, Any] = {
            "session_id": session_id,
            "format": format,
        }
        if filename:
            body["options"] = {"filename": filename}

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/documents/export",
                headers={**self._headers, "Content-Type": "application/json"},
                json=body,
            )
        self._raise_for_status(response, "export")
        content_type = response.headers.get("content-type", "application/octet-stream")
        logger.info(
            "SuperDocs export session=%s format=%s bytes=%s",
            session_id,
            format,
            len(response.content),
        )
        return response.content, content_type
