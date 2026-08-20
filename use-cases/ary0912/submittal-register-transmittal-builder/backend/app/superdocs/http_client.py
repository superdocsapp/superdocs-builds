import base64
import json
import uuid

import httpx

from app.core.config import settings


class SuperDocsHTTPClient:

    def __init__(self) -> None:
        if not settings.superdocs_api_key:
            raise RuntimeError(
                "SUPERDOCS_API_KEY is not configured."
            )

        self.base_url = settings.superdocs_base_url.rstrip("/")
        self.headers = {
            "Authorization": (
                f"Bearer {settings.superdocs_api_key}"
            ),
            "Content-Type": "application/json",
        }

    async def upload_document(
        self,
        filename: str,
        content: bytes,
    ) -> dict:
        # The current integration creates the session identifier locally
        # and sends the authoritative HTML with each chat request.
        session_id = f"submittal-{uuid.uuid4()}"
        document_html = content.decode("utf-8")
        return {
            "session_id": session_id,
            "filename": filename,
            "document_html": document_html,
        }

    async def edit_document(
        self,
        session_id: str,
        message: str,
        document_html: str,
        approval_mode: str = "ask_every_time",
    ) -> dict:
        payload = {
            "message": message,
            "session_id": session_id,
            "document_html": document_html,
            "approval_mode": approval_mode,
        }

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/async",
                headers=self.headers,
                json=payload,
            )

        response.raise_for_status()
        result = response.json()
        if not result.get("job_id"):
            raise RuntimeError(
                "SuperDocs async edit response did not include job_id."
            )
        return result

    async def get_job(self, job_id: str) -> dict:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.get(
                f"{self.base_url}/v1/jobs/{job_id}",
                headers=self.headers,
            )

        response.raise_for_status()
        result = response.json()

        # SuperDocs may return proposed_changes as a double-JSON-encoded
        # string (a JSON string containing an escaped JSON array). Detect
        # and parse it so downstream consumers always receive a list.
        for key in ("proposed_changes", "changes"):
            val = result.get(key)
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        result[key] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

        metadata = result.get("metadata")
        if isinstance(metadata, dict):
            pending = metadata.get("pending_changes")
            if isinstance(pending, str):
                try:
                    parsed = json.loads(pending)
                    if isinstance(parsed, list):
                        metadata["pending_changes"] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

        return result

    async def approve_change(
        self,
        session_id: str,
        job_id: str,
        change_id: str | None,
        approved: bool,
    ) -> dict:
        payload = {
            "job_id": job_id,
            "approved": approved,
        }
        if change_id:
            payload["change_id"] = change_id

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/{session_id}/approve",
                headers=self.headers,
                json=payload,
            )

        response.raise_for_status()
        return response.json()

    async def export_document(
        self,
        session_id: str,
        format: str = "docx",
        html: str | None = None,
        filename: str | None = None,
    ) -> dict:
        payload = {
            "session_id": session_id,
            "format": format,
        }
        if html is not None:
            payload["html"] = html
        if filename is not None:
            payload["filename"] = filename

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.base_url}/v1/documents/export",
                headers=self.headers,
                json=payload,
            )

        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            result = response.json()
            result.setdefault("format", format)
            result.setdefault("filename", filename)
            result.setdefault(
                "warnings",
                response.headers.get("X-Export-Warnings"),
            )
            return result

        return {
            "format": format,
            "filename": filename,
            "content_base64": base64.b64encode(
                response.content
            ).decode("ascii"),
            "content_type": content_type,
            "content_size": len(response.content),
            "warnings": response.headers.get("X-Export-Warnings"),
        }
