"""The live SuperDocs client.

A thin mapping onto the real REST API. Transient failures (429, 5xx, timeouts) retry with
exponential backoff and jitter, honouring ``Retry-After``; permanent 4xx fail fast with a
message that names the cause. Every contract below that differs from the published
documentation was established by calling the endpoint and reading what came back.
"""

from __future__ import annotations

import base64
import contextlib
import random
import time
from typing import Any

import httpx

from inspection_report.logging import get_logger
from inspection_report.superdocs.base import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    SessionBusyError,
    SuperDocsError,
    parse_document_html,
    parse_pending_changes,
    parse_status,
    parse_usage,
)
from inspection_report.superdocs.models import (
    ApprovalDecision,
    ApproveResult,
    ExportOptions,
    ExportResult,
    ImageUpload,
    Job,
    TemplateRef,
    UploadResult,
)

_log = get_logger("inspection_report.superdocs.live")
_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# A 409 `session_busy` means either "still processing" (worth waiting out) or "an earlier
# batch's proposals are still pending approval" (waiting cannot clear it — only deciding
# them can). We wait long enough to cover documented processing latency, then raise rather
# than stall for many minutes on a lock that will never lift.
_BUSY_WAIT_S = 5.0
_BUSY_RETRIES = 12


class LiveSuperDocsClient:
    """HTTP implementation of :class:`~inspection_report.superdocs.base.SuperDocsClient`."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.superdocs.app",
        max_retries: int = 5,
        backoff_base_s: float = 0.5,
    ) -> None:
        if not api_key:
            raise SuperDocsError(
                "PROVIDER=live needs SUPERDOCS_API_KEY. Set it in .env, or leave PROVIDER "
                "unset to run on the deterministic fake with no key."
            )
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(180.0),
        )
        self._max_retries = max_retries
        self._backoff = backoff_base_s

    # ------------------------------------------------------------------ transport

    def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        attempt = busy = 0
        while True:
            try:
                resp = self._client.request(method, path, json=json)
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise SuperDocsError(f"{method} {path}: {exc}") from exc
                self._sleep(attempt, None)
                attempt += 1
                continue
            if resp.status_code == 409 and "session_busy" in resp.text:
                if busy >= _BUSY_RETRIES:
                    raise SessionBusyError(
                        f"{path}: the session still holds a pending proposal set after "
                        f"{busy} checks. Decide and apply the outstanding changes before "
                        f"sending another batch."
                    )
                _log.info("session_busy_waiting", extra={"path": path, "attempt": busy})
                time.sleep(_BUSY_WAIT_S)
                busy += 1
                continue
            if resp.status_code in _RETRYABLE and attempt < self._max_retries:
                self._sleep(attempt, resp.headers.get("Retry-After"))
                attempt += 1
                continue
            if resp.status_code >= 400:
                raise SuperDocsError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
            return resp

    def _sleep(self, attempt: int, retry_after: str | None) -> None:
        delay = self._backoff * (2**attempt) + random.uniform(0, self._backoff)
        if retry_after:
            with contextlib.suppress(ValueError):
                delay = float(retry_after)
        time.sleep(delay)

    # ------------------------------------------------------- the minimum contract

    def upload_document(self, *, document_html: str, session_id: str) -> UploadResult:
        # The documented `document_html` body returns 422; the endpoint wants a base64 file
        # plus a filename. Verified live.
        data = self._request(
            "POST",
            "/v1/documents/upload-base64",
            json={
                "file_base64": base64.b64encode(document_html.encode()).decode(),
                "filename": f"{session_id}.html",
                "session_id": session_id,
                "return_html": True,
            },
        ).json()
        return UploadResult.model_validate(data)

    def chat_async(
        self,
        *,
        session_id: str,
        message: str,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
        thinking_depth: str = "balanced",
    ) -> str:
        data = self._request(
            "POST",
            "/v1/chat/async",
            json={
                "session_id": session_id,
                "message": message,
                "approval_mode": approval_mode,
                "model_tier": model_tier,
                "thinking_depth": thinking_depth,
            },
        ).json()
        return str(data["job_id"])

    def get_job(self, job_id: str) -> Job:
        data = self._request("GET", f"/v1/jobs/{job_id}").json()
        changes = (data.get("result") or {}).get("document_changes") or {}
        return Job(
            job_id=data.get("job_id", job_id),
            status=parse_status(data.get("status")),
            chunk_diffs=parse_pending_changes(data),
            document_html=parse_document_html(data),
            requires_approval=bool(changes.get("requires_approval")),
            usage=parse_usage(data),
            error=data.get("error"),
        )

    def approve(
        self, *, session_id: str, decisions: list[ApprovalDecision], job_id: str
    ) -> ApproveResult:
        # Keyed on `change_id`, not the documented `chunk_id` (which returns 500), and one
        # call per job: approving closes the job, so a second call for the rest of that
        # job's changes is refused with 400.
        data = self._request(
            "POST",
            f"/v1/chat/{session_id}/approve",
            json={
                "job_id": job_id,
                "approved": any(d.approved for d in decisions),
                "changes": [
                    {"change_id": d.change_id, "approved": d.approved, "feedback": d.feedback}
                    for d in decisions
                ],
            },
        ).json()
        return ApproveResult.model_validate(data)

    def export(
        self, *, session_id: str, fmt: str = "docx", options: ExportOptions | None = None
    ) -> ExportResult:
        body: dict[str, Any] = {"session_id": session_id, "format": fmt}
        if options is not None:
            body["options"] = options.model_dump(exclude_none=True)
        resp = self._request("POST", "/v1/documents/export", json=body)
        # The caller's name wins. Falling back to the session id would name a finished report
        # after an internal identifier, which is what someone reads off the file they were
        # handed — and since the export session is keyed by content hash, that identifier is
        # not even stable across a re-run.
        stem = (options.filename if options and options.filename else session_id).strip()
        return ExportResult(
            content=resp.content,
            content_type=resp.headers.get("content-type", _DOCX),
            filename=f"{stem}.{fmt}",
        )

    # -------------------------------------------------- images and templates

    def upload_image(
        self, *, data: bytes, filename: str, content_type: str = "image/png"
    ) -> ImageUpload:
        if len(data) > MAX_IMAGE_BYTES:
            raise SuperDocsError(
                f"{filename} is {len(data)} bytes; the image endpoint accepts at most "
                f"{MAX_IMAGE_BYTES}. Resize it before upload."
            )
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise SuperDocsError(
                f"{filename} is {content_type}; accepted types are {sorted(ALLOWED_IMAGE_TYPES)}."
            )
        payload = self._request(
            "POST",
            "/v1/documents/images/upload-base64",
            json={
                "image_base64": base64.b64encode(data).decode(),
                "filename": filename,
                "content_type": content_type,
            },
        ).json()
        # Only `url` is kept. `view_url` carries a 24-hour signature and would be stale
        # before most reports are finished; `url` is stable. Neither is ever logged.
        return ImageUpload.model_validate(payload)

    def upload_template(self, *, data: bytes, filename: str) -> TemplateRef:
        # `session_id` and `return_html` are accepted by the schema and do nothing here —
        # a template is never loaded into a session by this call. Omitted deliberately.
        payload = self._request(
            "POST",
            "/v1/templates/upload-base64",
            json={"filename": filename, "file_base64": base64.b64encode(data).decode()},
        ).json()
        return TemplateRef.model_validate(payload)

    def ops_remaining(self) -> int | None:
        """Operations left on the promotional bucket, without spending one to find out.

        `/v1/users/me/usage` and `/limits` reject API keys outright, which is misleading —
        they are published under the same bearer scheme as everything else. `promotions`
        accepts the key and carries the real numbers, so a build can check its own budget
        before starting a run rather than discovering it mid-report. Returns ``None`` if no
        promotional bucket is active, which is not an error.
        """
        try:
            payload = self._request("GET", "/v1/users/me/promotions").json()
        except SuperDocsError as exc:
            _log.info("ops_remaining_unavailable", extra={"error": str(exc)[:120]})
            return None
        for promo in payload.get("active") or []:
            remaining = promo.get("ops_remaining")
            if isinstance(remaining, int):
                return remaining
        return None

    def list_templates(self) -> list[TemplateRef]:
        payload = self._request("GET", "/v1/templates").json()
        return [TemplateRef.model_validate(t) for t in payload.get("templates", [])]

    def delete_template(self, template_id: str) -> None:
        self._request("DELETE", f"/v1/templates/{template_id}")

    # ------------------------------------------------------------- operational

    def continue_job(self, *, session_id: str, job_id: str, keep_going: bool) -> None:
        self._request(
            "POST",
            f"/v1/chat/{session_id}/continue",
            json={"job_id": job_id, "continue": keep_going},
        )

    def close(self) -> None:
        self._client.close()
