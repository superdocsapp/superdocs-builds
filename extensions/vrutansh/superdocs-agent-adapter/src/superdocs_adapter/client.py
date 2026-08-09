"""Small REST client for the four-call SuperDocs contract."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any, Mapping

import httpx

from .errors import ConfigurationError, InvalidResponseError, SuperDocsAPIError
from .models import ExportFormat, ExportedDocument, Job, UploadResult
from .parsing import parse_job, parse_upload, require_string


class SuperDocsClient:
    """HTTP transport with no dependency on an agent framework."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.superdocs.app",
        timeout: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ConfigurationError("SUPERDOCS_API_KEY is required")
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "SuperDocsClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _json(self, response: httpx.Response) -> Mapping[str, Any]:
        if not response.is_success:
            message = response.text[:500] or response.reason_phrase
            try:
                body = response.json()
                message = str(body.get("detail") or body.get("message") or message)
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
            raise SuperDocsAPIError(response.status_code, message)
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise InvalidResponseError("SuperDocs returned non-JSON data") from exc
        if not isinstance(body, Mapping):
            raise InvalidResponseError("SuperDocs JSON response must be an object")
        return body

    def upload_document(self, file_path: str | Path, session_id: str) -> UploadResult:
        path = Path(file_path)
        if not path.is_file():
            raise ConfigurationError(f"Input document does not exist: {path}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as stream:
            response = self._http.post(
                "/v1/documents/upload",
                files={"file": (path.name, stream, content_type)},
                data={"session_id": session_id, "open_mode": "replace"},
            )
        return parse_upload(self._json(response), session_id)

    def start_edit(
        self,
        session_id: str,
        instruction: str,
        *,
        model_tier: str = "core",
        thinking_depth: str = "balanced",
    ) -> str:
        if not instruction.strip():
            raise ConfigurationError("Edit instruction cannot be empty")
        response = self._http.post(
            "/v1/chat/async",
            json={
                "message": instruction,
                "session_id": session_id,
                "approval_mode": "ask_every_time",
                "response_mode": "compact",
                "model_tier": model_tier,
                "thinking_depth": thinking_depth,
            },
        )
        return require_string(self._json(response), "job_id")

    def get_job(self, job_id: str, *, compact: bool = True) -> Job:
        response = self._http.get(f"/v1/jobs/{job_id}", params={"compact": compact})
        return parse_job(self._json(response))

    def approve_changes(self, session_id: str, job: Job, *, approved: bool = True) -> None:
        changes = [
            {"change_id": change.change_id, "approved": approved}
            for change in job.proposed_changes
        ]
        response = self._http.post(
            f"/v1/chat/{session_id}/approve",
            json={"job_id": job.job_id, "approved": approved, "changes": changes},
        )
        self._json(response)

    def export_document(
        self,
        session_id: str,
        *,
        export_format: ExportFormat = ExportFormat.TXT,
        filename: str = "superdocs-output",
    ) -> ExportedDocument:
        response = self._http.post(
            "/v1/documents/export",
            json={
                "session_id": session_id,
                "format": export_format.value,
                "options": {"filename": filename},
            },
        )
        if not response.is_success:
            self._json(response)
        content_type = response.headers.get("content-type")
        if content_type and "application/json" in content_type:
            body = self._json(response)
            download_url = body.get("download_url")
            if not isinstance(download_url, str):
                raise InvalidResponseError("Export JSON did not contain download_url")
            download = self._http.get(download_url)
            if not download.is_success:
                raise SuperDocsAPIError(download.status_code, "Export download failed")
            response = download
            content_type = response.headers.get("content-type")
        suffix = "md" if export_format is ExportFormat.MARKDOWN else export_format.value
        output_name = filename if filename.endswith(f".{suffix}") else f"{filename}.{suffix}"
        return ExportedDocument(response.content, export_format, output_name, content_type)
