from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


VALID_EXPORT_FORMATS = {"docx", "pdf", "html", "markdown", "txt", "doc"}


class SuperDocsError(RuntimeError):
    pass


@dataclass(frozen=True)
class PendingChange:
    change_id: str
    chunk_id: str | None
    document_id: str | None
    old_html: str
    new_html: str
    ai_explanation: str | None


@dataclass(frozen=True)
class ApprovedDocument:
    session_id: str
    job_id: str
    changes: tuple[PendingChange, ...]


class SuperDocsClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.superdocs.app",
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise SuperDocsError(
                "SuperDocs API key is missing. Set SUPERDOCS_API_KEY in the environment."
            )
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def draft_with_approval(
        self,
        *,
        document_html: str,
        message: str,
        session_id: str,
        poll_interval_seconds: float = 2.0,
        max_polls: int = 90,
        max_elapsed_seconds: float = 300.0,
    ) -> ApprovedDocument:
        if max_polls <= 0:
            raise SuperDocsError("polling stopped: max_polls must be positive. Increase max_polls.")
        uploaded_html = self._upload_html_with_warmup_retry(document_html, session_id)
        job_id = self._start_async_chat(
            document_html=uploaded_html,
            message=message,
            session_id=session_id,
        )
        changes = self._poll_for_approval(
            job_id=job_id,
            poll_interval_seconds=poll_interval_seconds,
            max_polls=max_polls,
            max_elapsed_seconds=max_elapsed_seconds,
        )
        for change in changes:
            self._approve_change(session_id=session_id, job_id=job_id, change_id=change.change_id)
        return ApprovedDocument(session_id=session_id, job_id=job_id, changes=changes)

    def export(self, *, session_id: str, fmt: str) -> bytes:
        if fmt not in VALID_EXPORT_FORMATS:
            valid = ", ".join(f"'{value}'" for value in sorted(VALID_EXPORT_FORMATS))
            raise SuperDocsError(
                f"export failed: format '{fmt}' is not valid. Use {valid}."
            )
        response = self._request(
            "POST",
            "/v1/documents/export",
            json={"session_id": session_id, "format": fmt},
        )
        return response.content

    def _upload_html_with_warmup_retry(self, document_html: str, session_id: str) -> str:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self._request(
                    "POST",
                    "/v1/documents/upload",
                    files={"file": ("corrective-plan.html", document_html, "text/html")},
                    data={"session_id": session_id},
                )
                payload = _json_response(response, "upload")
                html = payload.get("html")
                if not isinstance(html, str) or not html:
                    raise SuperDocsError(
                        "upload failed: response did not include html. Retry the upload or check the API response shape."
                    )
                return html
            except (httpx.HTTPError, SuperDocsError) as error:
                last_error = error
                if attempt == 1:
                    break
        raise SuperDocsError(
            f"upload failed after warm-up retry: {last_error}. Check network access and SUPERDOCS_API_KEY."
        )

    def _start_async_chat(self, *, document_html: str, message: str, session_id: str) -> str:
        response = self._request(
            "POST",
            "/v1/chat/async",
            json={
                "message": message,
                "session_id": session_id,
                "document_html": document_html,
                "approval_mode": "ask_every_time",
            },
        )
        payload = _json_response(response, "chat")
        job_id = payload.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise SuperDocsError(
                "chat failed: async response did not include job_id. Use /v1/chat/async, not /v1/chat."
            )
        return job_id

    def _poll_for_approval(
        self,
        *,
        job_id: str,
        poll_interval_seconds: float,
        max_polls: int,
        max_elapsed_seconds: float,
    ) -> tuple[PendingChange, ...]:
        started = time.monotonic()
        last_status = "unknown"
        for poll_count in range(1, max_polls + 1):
            response = self._request("GET", f"/v1/jobs/{job_id}")
            payload = _json_response(response, "job polling")
            last_status = str(payload.get("status", "unknown"))
            if last_status == "awaiting_approval":
                return _pending_changes(payload)
            if last_status in {"failed", "cancelled", "error"}:
                raise SuperDocsError(
                    f"job failed: status is '{last_status}'. Inspect the job error and retry the request."
                )
            if time.monotonic() - started >= max_elapsed_seconds:
                raise SuperDocsError(
                    f"polling stopped after {poll_count} polls and {max_elapsed_seconds:.0f}s with status '{last_status}'. Increase max_elapsed_seconds or inspect job {job_id}."
                )
            time.sleep(poll_interval_seconds)
        raise SuperDocsError(
            f"polling stopped after {max_polls} polls with status '{last_status}'. Increase max_polls or inspect job {job_id}."
        )

    def _approve_change(self, *, session_id: str, job_id: str, change_id: str) -> None:
        payload = {
            "job_id": job_id,
            "change_id": change_id,
            "approved": True,
        }
        response = self._request("POST", f"/v1/chat/{session_id}/approve", json=payload)
        result = _json_response(response, "approval")
        if result.get("status") != "ok":
            raise SuperDocsError(
                "approval failed: API did not return status 'ok'. Retry approval before exporting."
            )

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(
            method,
            f"{self._base_url}{path}",
            headers=self._headers,
            **kwargs,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = _error_detail(response)
            raise SuperDocsError(
                f"{method} {path} failed with HTTP {response.status_code}: {detail}. Check request fields and retry."
            ) from error
        return response


def _json_response(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError as error:
        raise SuperDocsError(
            f"{operation} failed: response was not JSON. Check the SuperDocs API status and retry."
        ) from error
    if not isinstance(payload, dict):
        raise SuperDocsError(
            f"{operation} failed: response JSON was not an object. Check the API response shape."
        )
    return payload


def _pending_changes(payload: dict[str, Any]) -> tuple[PendingChange, ...]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise SuperDocsError(
            "approval failed: job metadata is missing. Retry polling or inspect the job response."
        )
    raw_changes = metadata.get("pending_changes")
    if isinstance(raw_changes, str):
        raw_changes = json.loads(raw_changes)
    if not isinstance(raw_changes, list) or not raw_changes:
        raise SuperDocsError(
            "approval failed: pending_changes is empty. Ask SuperDocs to produce changes before approval."
        )
    changes: list[PendingChange] = []
    for raw in raw_changes:
        if not isinstance(raw, dict):
            raise SuperDocsError(
                "approval failed: pending_changes contained a non-object item. Inspect the job response."
            )
        change_id = raw.get("change_id")
        if not isinstance(change_id, str) or not change_id:
            raise SuperDocsError(
                "approval failed: pending change has no change_id. Retry the async chat request."
            )
        changes.append(
            PendingChange(
                change_id=change_id,
                chunk_id=_optional_str(raw.get("chunk_id")),
                document_id=_optional_str(raw.get("document_id")),
                old_html=str(raw.get("old_html", "")),
                new_html=str(raw.get("new_html", "")),
                ai_explanation=_optional_str(raw.get("ai_explanation")),
            )
        )
    return tuple(changes)


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return response.text[:500]
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        return json.dumps(payload, sort_keys=True)[:500]
    return str(payload)[:500]


def load_api_key_from_env_file(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("SUPERDOCS_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None

