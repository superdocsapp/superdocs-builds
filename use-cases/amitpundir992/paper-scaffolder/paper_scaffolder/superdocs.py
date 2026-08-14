"""Typed adapter for the documented SuperDocs REST workflow."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import quote

from .http_transport import (
    HttpRequest,
    HttpResponse,
    HttpTransport,
    TransportNetworkError,
    TransportTimeoutError,
    UrllibHttpTransport,
)


DEFAULT_BASE_URL = "https://api.superdocs.app"
_JOB_STATUSES = {
    "pending",
    "in_progress",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
}
_OPERATIONS = {"edit", "create", "delete"}
_EXPORT_FORMATS = {"docx", "pdf", "html", "markdown", "txt", "doc"}


class SuperDocsError(RuntimeError):
    """Base class for safe, user-facing integration failures."""

    code = "superdocs_error"


class SuperDocsConfigurationError(SuperDocsError):
    code = "superdocs_not_configured"


class SuperDocsAuthenticationError(SuperDocsError):
    code = "superdocs_authentication_failed"


class SuperDocsNotFoundError(SuperDocsError):
    code = "superdocs_resource_not_found"


class SuperDocsRequestError(SuperDocsError):
    code = "superdocs_request_failed"


class SuperDocsMalformedResponseError(SuperDocsError):
    code = "superdocs_malformed_response"


class SuperDocsTimeoutError(SuperDocsError):
    code = "superdocs_timeout"


class SuperDocsNetworkError(SuperDocsError):
    code = "superdocs_network_error"


@dataclass(frozen=True)
class SuperDocsSettings:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 30.0

    @classmethod
    def from_environment(cls) -> SuperDocsSettings:
        api_key = os.getenv("SUPERDOCS_API_KEY", "").strip()
        if not api_key:
            raise SuperDocsConfigurationError(
                "SuperDocs is not configured. Set SUPERDOCS_API_KEY on the server."
            )
        base_url = os.getenv("SUPERDOCS_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
        try:
            timeout = float(os.getenv("SUPERDOCS_TIMEOUT_SECONDS", "30"))
        except ValueError as exc:
            raise SuperDocsConfigurationError(
                "SUPERDOCS_TIMEOUT_SECONDS must be a number."
            ) from exc
        if not base_url.startswith(("https://", "http://")):
            raise SuperDocsConfigurationError(
                "SUPERDOCS_BASE_URL must be an HTTP or HTTPS URL."
            )
        if timeout <= 0:
            raise SuperDocsConfigurationError(
                "SUPERDOCS_TIMEOUT_SECONDS must be greater than zero."
            )
        return cls(api_key=api_key, base_url=base_url, timeout_seconds=timeout)


@dataclass(frozen=True)
class UploadedDocument:
    html: str
    session_id: str
    filename: str
    chunks_count: int
    version_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EditJob:
    job_id: str
    session_id: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ProposedChange:
    change_id: str
    operation: str
    chunk_id: str | None
    document_id: str | None
    old_html: str | None
    new_html: str | None
    ai_explanation: str | None
    insert_after_chunk_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    session_id: str
    status: str
    progress: int
    error: str | None
    awaiting_kind: str | None
    proposed_changes: tuple[ProposedChange, ...]
    updated_html: str | None
    response: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "proposed_changes": [change.to_dict() for change in self.proposed_changes],
        }


@dataclass(frozen=True)
class ExportedDocument:
    content: bytes
    content_type: str
    filename: str


class SuperDocsPort(Protocol):
    def upload_document(
        self, *, filename: str, content: bytes, session_id: str
    ) -> UploadedDocument:
        """POST a multipart file to the documented active-document upload route."""

    def send_edit_instruction(
        self, *, session_id: str, instruction: str, document_html: str | None = None
    ) -> EditJob:
        """Start an async edit in mandatory human-review mode."""

    def get_job(self, *, job_id: str) -> JobSnapshot:
        """Poll job state and pending proposed changes."""

    def get_proposed_changes(self, *, job_id: str) -> tuple[ProposedChange, ...]:
        """Retrieve item-level changes from job metadata."""

    def approve_change(
        self, *, session_id: str, job_id: str, change_id: str
    ) -> Mapping[str, Any]:
        """Approve one documented change identifier."""

    def reject_change(
        self,
        *,
        session_id: str,
        job_id: str,
        change_id: str,
        feedback: str = "",
    ) -> Mapping[str, Any]:
        """Deny one documented change identifier, optionally with feedback."""

    def export_document(
        self, *, session_id: str, file_format: str, filename: str
    ) -> ExportedDocument:
        """Export the current documented session state."""


def _decode_json_layers(value: Any) -> Any:
    decoded = value
    for _ in range(2):
        if not isinstance(decoded, str):
            break
        try:
            decoded = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise SuperDocsMalformedResponseError(
                "SuperDocs returned invalid JSON-encoded proposed-change content."
            ) from exc
    return decoded


def parse_proposed_change_content(content: str | dict[str, Any]) -> dict[str, Any]:
    """Decode a proposed change object, including one nested JSON encoding."""

    decoded = _decode_json_layers(content)
    if not isinstance(decoded, dict):
        raise SuperDocsMalformedResponseError(
            "SuperDocs proposed-change content must decode to an object."
        )
    return decoded


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SuperDocsMalformedResponseError(
            f"SuperDocs response is missing the required '{key}' field."
        )
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SuperDocsMalformedResponseError(
            f"SuperDocs response field '{field}' has an invalid type."
        )
    return value


def _parse_change(value: Any) -> ProposedChange:
    data = parse_proposed_change_content(value) if isinstance(value, str) else value
    if not isinstance(data, dict):
        raise SuperDocsMalformedResponseError(
            "A SuperDocs pending change is not an object."
        )
    operation = _required_string(data, "operation")
    if operation not in _OPERATIONS:
        raise SuperDocsMalformedResponseError(
            "SuperDocs returned an unknown proposed-change operation."
        )
    return ProposedChange(
        change_id=_required_string(data, "change_id"),
        operation=operation,
        chunk_id=_optional_string(data.get("chunk_id"), "chunk_id"),
        document_id=_optional_string(data.get("document_id"), "document_id"),
        old_html=_optional_string(data.get("old_html"), "old_html"),
        new_html=_optional_string(data.get("new_html"), "new_html"),
        ai_explanation=_optional_string(data.get("ai_explanation"), "ai_explanation"),
        insert_after_chunk_id=_optional_string(
            data.get("insert_after_chunk_id"), "insert_after_chunk_id"
        ),
    )


class SuperDocsHttpAdapter:
    """Server-side REST adapter using the live documented API contract."""

    def __init__(
        self,
        settings: SuperDocsSettings,
        transport: HttpTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or UrllibHttpTransport()

    def upload_document(
        self, *, filename: str, content: bytes, session_id: str
    ) -> UploadedDocument:
        if not content:
            raise SuperDocsRequestError("Cannot upload an empty manuscript.")
        body, content_type = self._multipart_document(filename, content, session_id)
        data = self._request_json(
            "POST",
            "/v1/documents/upload",
            body=body,
            content_type=content_type,
        )
        chunks_count = data.get("chunks_count")
        if not isinstance(chunks_count, int):
            raise SuperDocsMalformedResponseError(
                "SuperDocs upload response has an invalid chunks_count field."
            )
        return UploadedDocument(
            html=_required_string(data, "html"),
            session_id=_required_string(data, "session_id"),
            filename=_required_string(data, "filename"),
            chunks_count=chunks_count,
            version_id=_optional_string(data.get("version_id"), "version_id"),
        )

    def send_edit_instruction(
        self, *, session_id: str, instruction: str, document_html: str | None = None
    ) -> EditJob:
        if not instruction.strip():
            raise SuperDocsRequestError("An edit instruction is required.")
        if document_html is not None and not document_html.strip():
            raise SuperDocsRequestError("Document HTML cannot be empty when supplied.")
        payload: dict[str, Any] = {
            "message": instruction.strip(),
            "session_id": session_id,
            "approval_mode": "ask_every_time",
            "response_mode": "full",
        }
        if document_html is not None:
            payload["document_html"] = document_html
        data = self._request_json(
            "POST",
            "/v1/chat/async",
            json_body=payload,
        )
        status = _required_string(data, "status")
        if status not in _JOB_STATUSES:
            raise SuperDocsMalformedResponseError(
                "SuperDocs returned an unknown job status."
            )
        message = data.get("message", "")
        if not isinstance(message, str):
            raise SuperDocsMalformedResponseError(
                "SuperDocs edit response has an invalid message field."
            )
        return EditJob(
            job_id=_required_string(data, "job_id"),
            session_id=_required_string(data, "session_id"),
            status=status,
            message=message,
        )

    def get_job(self, *, job_id: str) -> JobSnapshot:
        data = self._request_json("GET", f"/v1/jobs/{quote(job_id, safe='')}")
        status = _required_string(data, "status")
        if status not in _JOB_STATUSES:
            raise SuperDocsMalformedResponseError(
                "SuperDocs returned an unknown job status."
            )
        progress = data.get("progress")
        if not isinstance(progress, int):
            raise SuperDocsMalformedResponseError(
                "SuperDocs job response has an invalid progress field."
            )

        metadata_value = data.get("metadata") or {}
        metadata = _decode_json_layers(metadata_value)
        if not isinstance(metadata, dict):
            raise SuperDocsMalformedResponseError(
                "SuperDocs job metadata must be an object."
            )
        pending_value = _decode_json_layers(metadata.get("pending_changes") or [])
        if not isinstance(pending_value, list):
            raise SuperDocsMalformedResponseError(
                "SuperDocs pending_changes must be an array."
            )

        result_value = _decode_json_layers(data.get("result") or {})
        if not isinstance(result_value, dict):
            raise SuperDocsMalformedResponseError(
                "SuperDocs job result must be an object."
            )
        changes_value = _decode_json_layers(result_value.get("document_changes") or {})
        if not isinstance(changes_value, dict):
            raise SuperDocsMalformedResponseError(
                "SuperDocs document_changes must be an object."
            )

        awaiting_kind = _optional_string(metadata.get("awaiting_kind"), "awaiting_kind")
        response_text = _optional_string(result_value.get("response"), "response")
        return JobSnapshot(
            job_id=_required_string(data, "job_id"),
            session_id=_required_string(data, "session_id"),
            status=status,
            progress=progress,
            error=_optional_string(data.get("error"), "error"),
            awaiting_kind=awaiting_kind,
            proposed_changes=tuple(_parse_change(item) for item in pending_value),
            updated_html=_optional_string(
                changes_value.get("updated_html"), "updated_html"
            ),
            response=response_text,
        )

    def get_proposed_changes(self, *, job_id: str) -> tuple[ProposedChange, ...]:
        return self.get_job(job_id=job_id).proposed_changes

    def approve_change(
        self, *, session_id: str, job_id: str, change_id: str
    ) -> Mapping[str, Any]:
        return self._submit_decision(
            session_id=session_id,
            job_id=job_id,
            change_id=change_id,
            approved=True,
            feedback="",
        )

    def reject_change(
        self,
        *,
        session_id: str,
        job_id: str,
        change_id: str,
        feedback: str = "",
    ) -> Mapping[str, Any]:
        return self._submit_decision(
            session_id=session_id,
            job_id=job_id,
            change_id=change_id,
            approved=False,
            feedback=feedback,
        )

    def export_document(
        self, *, session_id: str, file_format: str, filename: str
    ) -> ExportedDocument:
        if file_format not in _EXPORT_FORMATS:
            raise SuperDocsRequestError("Unsupported export format.")
        response = self._request(
            "POST",
            "/v1/documents/export",
            json_body={
                "session_id": session_id,
                "format": file_format,
                "options": {"filename": filename},
            },
        )
        if not response.body:
            raise SuperDocsMalformedResponseError(
                "SuperDocs returned an empty export."
            )
        content_type = response.headers.get(
            "content-type", "application/octet-stream"
        ).split(";", 1)[0]
        returned_filename = self._response_filename(
            response.headers.get("content-disposition"), filename, file_format
        )
        return ExportedDocument(response.body, content_type, returned_filename)

    def _submit_decision(
        self,
        *,
        session_id: str,
        job_id: str,
        change_id: str,
        approved: bool,
        feedback: str,
    ) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "change_id": change_id,
            "approved": approved,
        }
        if feedback:
            payload["feedback"] = feedback
        return self._request_json(
            "POST",
            f"/v1/chat/{quote(session_id, safe='')}/approve",
            json_body=payload,
            allow_empty_object=True,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str = "application/json",
        json_body: Mapping[str, Any] | None = None,
        allow_empty_object: bool = False,
    ) -> dict[str, Any]:
        response = self._request(
            method,
            path,
            body=body,
            content_type=content_type,
            json_body=json_body,
        )
        if not response.body and allow_empty_object:
            return {}
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuperDocsMalformedResponseError(
                "SuperDocs returned a malformed JSON response."
            ) from exc
        decoded = _decode_json_layers(decoded)
        if not isinstance(decoded, dict):
            raise SuperDocsMalformedResponseError(
                "SuperDocs response must be a JSON object."
            )
        return decoded

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str = "application/json",
        json_body: Mapping[str, Any] | None = None,
    ) -> HttpResponse:
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Accept": "application/json, application/octet-stream, */*",
        }
        if body is not None:
            headers["Content-Type"] = content_type
        request = HttpRequest(
            method=method,
            url=f"{self._settings.base_url}{path}",
            headers=headers,
            body=body,
            timeout_seconds=self._settings.timeout_seconds,
        )
        try:
            response = self._transport.send(request)
        except TransportTimeoutError as exc:
            raise SuperDocsTimeoutError(
                "SuperDocs did not respond before the configured timeout."
            ) from exc
        except TransportNetworkError as exc:
            raise SuperDocsNetworkError(
                "Could not connect to SuperDocs. Check the network and try again."
            ) from exc
        self._raise_for_status(response)
        return response

    @staticmethod
    def _raise_for_status(response: HttpResponse) -> None:
        if 200 <= response.status_code < 300:
            return
        if response.status_code in {401, 403}:
            raise SuperDocsAuthenticationError(
                "SuperDocs authentication failed. Check the server-side API key."
            )
        if response.status_code == 404:
            raise SuperDocsNotFoundError(
                "The requested SuperDocs session, job, document, or change was not found."
            )
        if response.status_code in {408, 504}:
            raise SuperDocsTimeoutError("The SuperDocs request timed out.")
        if response.status_code == 429:
            raise SuperDocsRequestError(
                "SuperDocs rate or operation limits were reached. Try again later."
            )
        raise SuperDocsRequestError(
            f"SuperDocs rejected the request with status {response.status_code}."
        )

    @staticmethod
    def _multipart_document(
        filename: str, content: bytes, session_id: str
    ) -> tuple[bytes, str]:
        safe_filename = Path(filename).name.replace('"', "").replace("\r", "").replace("\n", "")
        boundary = f"paper-scaffolder-{uuid.uuid4().hex}"
        parts = [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="session_id"\r\n\r\n',
            session_id.encode("utf-8"),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="file"; '
                f'filename="{safe_filename}"\r\n'
            ).encode("utf-8"),
            b"Content-Type: text/html; charset=utf-8\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        return b"".join(parts), f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _response_filename(
        content_disposition: str | None, fallback: str, file_format: str
    ) -> str:
        if content_disposition:
            match = re.search(r'filename="?([^";]+)', content_disposition)
            if match:
                return Path(match.group(1)).name
        extension = "md" if file_format == "markdown" else file_format
        return f"{Path(fallback).stem}.{extension}"
