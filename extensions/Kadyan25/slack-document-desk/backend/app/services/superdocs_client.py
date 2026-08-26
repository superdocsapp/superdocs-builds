"""Thin REST client for the four-call SuperDocs contract, plus the calls needed to
resolve document ids and list saved documents. Every path/field below was confirmed
against a live account during Phase 0/1 exploration (see architecture.md), not guessed
from the docs alone — the docs' own OpenAPI schemas leave several 200 responses typed
as `{}`.
"""
import base64
import re

import httpx

from app.config import settings


class SessionBusyError(Exception):
    """SuperDocs returns 409 on chat_async when the session already has a job in
    flight or awaiting approval — only one active job per session. Surfaced as a
    typed exception so the caller can tell the user to resolve the pending change
    first, rather than crashing on a raw httpx error."""


class SuperDocsClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._client = httpx.Client(
            base_url=base_url or settings.superdocs_api_base_url,
            headers={"Authorization": f"Bearer {api_key or settings.superdocs_api_key}"},
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def upload_document(self, session_id: str, filename: str, content: bytes) -> dict:
        """Uploads content into `session_id` as the active document, then resolves the
        session-local and durable document ids (the upload response itself carries neither).
        Returns {"document_id": ..., "durable_document_id": ..., "title": ...}.
        """
        self._client.post(
            "/v1/documents/upload-base64",
            json={
                "filename": filename,
                "file_base64": base64.b64encode(content).decode("ascii"),
                "session_id": session_id,
            },
        ).raise_for_status()

        resp = self._client.get(f"/v1/sessions/{session_id}/documents")
        resp.raise_for_status()
        documents = resp.json()["documents"]
        focused = next((d for d in documents if d.get("focused")), documents[0])
        return {
            "document_id": focused["document_id"],
            "durable_document_id": focused.get("durable_document_id"),
            "title": focused.get("title", filename),
        }

    def chat_async(
        self,
        session_id: str,
        message: str,
        document_id: str | None = None,
        approval_mode: str = "ask_every_time",
    ) -> dict:
        payload = {"session_id": session_id, "message": message, "approval_mode": approval_mode}
        if document_id:
            payload["document_id"] = document_id
        resp = self._client.post("/v1/chat/async", json=payload)
        if resp.status_code == 409:
            raise SessionBusyError(
                f"session {session_id} already has an active job (HTTP 409)"
            )
        resp.raise_for_status()
        return resp.json()

    def get_job(self, job_id: str) -> dict:
        resp = self._client.get(f"/v1/jobs/{job_id}")
        resp.raise_for_status()
        return resp.json()

    def approve_change(
        self, session_id: str, job_id: str, approved: bool, change_id: str | None = None
    ) -> dict:
        payload = {"job_id": job_id, "approved": approved}
        if change_id:
            payload["change_id"] = change_id
        resp = self._client.post(f"/v1/chat/{session_id}/approve", json=payload)
        resp.raise_for_status()
        return resp.json()

    def export_document(self, session_id: str, format: str = "docx") -> dict:
        """Confirmed live against a real key: SuperDocs returns the exported file's raw
        bytes directly (a binary body + Content-Disposition header), not a JSON
        download-URL response as originally assumed during Phase 0 exploration — calling
        .json() on it raises UnicodeDecodeError. Returns {"filename", "content" (bytes),
        "content_type"}."""
        resp = self._client.post(
            "/v1/documents/export", json={"session_id": session_id, "format": format}
        )
        resp.raise_for_status()
        disposition = resp.headers.get("content-disposition", "")
        match = re.search(r'filename="([^"]+)"', disposition)
        filename = match.group(1) if match else f"export.{format}"
        return {
            "filename": filename,
            "content": resp.content,
            "content_type": resp.headers.get("content-type", "application/octet-stream"),
        }

    def list_documents(self, limit: int = 50, offset: int = 0) -> dict:
        resp = self._client.get(
            "/v1/documents", params={"limit": limit, "offset": offset}
        )
        resp.raise_for_status()
        return resp.json()
