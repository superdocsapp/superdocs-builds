"""Small REST client for the four-call SuperDocs contract."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from .errors import ConfigurationError, InvalidResponseError, SuperDocsAPIError
from .models import ExportedDocument, ExportFormat, Job, UploadResult
from .parsing import parse_job, parse_upload, require_string

SUPPORTED_INPUT_SUFFIXES = {".pdf", ".docx", ".txt", ".rtf", ".md", ".html", ".htm", ".tex", ".zip"}
DEFAULT_LARGE_UPLOAD_THRESHOLD = 20 * 1024 * 1024
MAX_UPLOAD_SIZE = 100 * 1024 * 1024


class SuperDocsClient:
    """HTTP transport with no dependency on an agent framework."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.superdocs.app",
        timeout: float = 60.0,
        http_client: httpx.Client | None = None,
        upload_http_client: httpx.Client | None = None,
        large_upload_threshold: int = DEFAULT_LARGE_UPLOAD_THRESHOLD,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ConfigurationError(
                "SUPERDOCS_API_KEY is required; set it in the environment before a live run"
            )
        self._owns_client = http_client is None
        self._owns_upload_client = upload_http_client is None
        self._large_upload_threshold = large_upload_threshold
        self._http = http_client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=timeout,
        )
        self._upload_http = upload_http_client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()
        if self._owns_upload_client:
            self._upload_http.close()

    def __enter__(self) -> SuperDocsClient:
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
            suggestions = {
                401: "verify SUPERDOCS_API_KEY and its access",
                413: "use the large-file upload path or reduce the payload",
                415: "use PDF, DOCX, TXT, RTF, Markdown, HTML, TeX, or a LaTeX ZIP",
                429: "wait for the rate-limit window before retrying",
            }
            suggestion = suggestions.get(response.status_code)
            if response.status_code >= 500:
                suggestion = "retry later using the saved checkpoint; do not start a new edit"
            if suggestion:
                message = f"{message}. Suggested fix: {suggestion}"
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
            raise ConfigurationError(
                f"Input document does not exist: {path}; verify the file path and retry"
            )
        if path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
            raise ConfigurationError(
                f"Unsupported input type {path.suffix or '<none>'}; use PDF, DOCX, TXT, RTF, "
                "Markdown, HTML, TeX, or a LaTeX ZIP"
            )
        size_bytes = path.stat().st_size
        if size_bytes <= 0:
            raise ConfigurationError("Input document is empty; provide a non-empty document")
        if size_bytes > MAX_UPLOAD_SIZE:
            raise ConfigurationError(
                "Input document exceeds SuperDocs' 100 MB upload limit; split the document "
                "or contact SuperDocs support"
            )
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if size_bytes > self._large_upload_threshold:
            return self._upload_large_document(
                path,
                session_id,
                content_type=content_type,
                size_bytes=size_bytes,
            )
        with path.open("rb") as stream:
            response = self._http.post(
                "/v1/documents/upload",
                files={"file": (path.name, stream, content_type)},
                data={"session_id": session_id, "open_mode": "replace"},
            )
        return parse_upload(self._json(response), session_id)

    def _upload_large_document(
        self,
        path: Path,
        session_id: str,
        *,
        content_type: str,
        size_bytes: int,
    ) -> UploadResult:
        request = self._http.post(
            "/v1/uploads",
            json={
                "filename": path.name,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "purpose": "document",
            },
        )
        upload = self._json(request)
        upload_id = require_string(upload, "upload_id")
        upload_url = require_string(upload, "upload_url")
        with path.open("rb") as stream:
            transferred = self._upload_http.put(
                upload_url,
                content=stream,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(size_bytes),
                },
            )
        if not transferred.is_success:
            raise SuperDocsAPIError(
                transferred.status_code,
                "Large-file transfer failed; request a fresh upload URL and retry before editing",
            )
        processed = self._http.post(
            f"/v1/uploads/{upload_id}/process",
            json={
                "session_id": session_id,
                "filename": path.name,
                "parse_mode": "document",
                "return_html": False,
            },
        )
        return parse_upload(self._json(processed), session_id)

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

    def list_session_jobs(self, session_id: str, *, limit: int = 1) -> tuple[Job, ...]:
        """Return newest session jobs, used to close the start-edit checkpoint race."""
        response = self._http.get(
            f"/v1/sessions/{session_id}/jobs",
            params={"limit": limit, "compact": True},
        )
        body = self._json(response)
        jobs = body.get("jobs")
        if not isinstance(jobs, list):
            raise InvalidResponseError("Session job list must contain a jobs array")
        return tuple(parse_job(item) for item in jobs if isinstance(item, Mapping))

    def approve_changes(self, session_id: str, job: Job, *, approved: bool = True) -> None:
        changes = [
            {"change_id": change.change_id, "approved": approved} for change in job.proposed_changes
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
                raise InvalidResponseError(
                    "Export JSON did not contain download_url; retry export "
                    "without repeating the edit"
                )
            download = self._http.get(download_url)
            if not download.is_success:
                raise SuperDocsAPIError(
                    download.status_code,
                    "Export download failed; request a fresh export URL without repeating the edit",
                )
            response = download
            content_type = response.headers.get("content-type")
        suffix = "md" if export_format is ExportFormat.MARKDOWN else export_format.value
        output_name = filename if filename.endswith(f".{suffix}") else f"{filename}.{suffix}"
        return ExportedDocument(response.content, export_format, output_name, content_type)
