"""Small, fail-closed SuperDocs adapter for the M0 contract spike."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict
from dotenv import load_dotenv

load_dotenv()

LOG = logging.getLogger("linecard.superdocs")
_SECRET = re.compile(r"(Bearer\s+|sk_[A-Za-z0-9]+|lce_[A-Za-z0-9]+|https?://[^\s]+)", re.I)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UploadUrlResponse(StrictModel):
    upload_id: str
    upload_url: str
    expires_at: str
    expires_in_seconds: int
    max_size_bytes: int
    curl_example: str


class AsyncChatResponse(StrictModel):
    job_id: str
    session_id: str
    status: str


class ApprovalDecision(StrictModel):
    change_id: str
    approved: bool
    feedback: str | None = None


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in {"authorization", "api_key", "upload_url", "curl_example", "cookie"} else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _SECRET.sub("[REDACTED]", value)
    return value


class OperationBudgetExceeded(RuntimeError):
    pass


@dataclass
class OperationBudget:
    cap: int = 1
    used: int = 0

    def consume(self, label: str) -> None:
        if self.used >= self.cap:
            raise OperationBudgetExceeded(f"operation budget exhausted before {label}")
        self.used += 1


class SuperDocsClient:
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, budget: OperationBudget | None = None, transport: httpx.BaseTransport | None = None):
        self.base_url = (base_url or os.getenv("SUPERDOCS_BASE_URL") or "https://api.superdocs.app").rstrip("/")
        self.api_key = api_key or os.getenv("SUPERDOCS_API_KEY")
        self.budget = budget or OperationBudget(int(os.getenv("LINECARD_LIVE_OPERATION_BUDGET", "1")))
        self.client = httpx.Client(base_url=self.base_url, timeout=httpx.Timeout(20.0, connect=10.0), transport=transport, follow_redirects=True, headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})

    def _request(self, method: str, path: str, *, billable: bool = False, **kwargs: Any) -> httpx.Response:
        if billable:
            self.budget.consume(f"{method} {path}")
        safe_kwargs = {k: redact(v) for k, v in kwargs.items() if k != "headers"}
        LOG.info("request method=%s path=%s payload=%s", method, path, safe_kwargs)
        response = self.client.request(method, path, **kwargs)
        try:
            body = redact(response.json())
        except ValueError:
            body = {"content_type": response.headers.get("content-type"), "bytes": len(response.content)}
        LOG.info("response status=%s body=%s", response.status_code, body)
        response.raise_for_status()
        return response

    def upload_url(self, filename: str, size_bytes: int, content_type: str | None = None) -> dict[str, Any]:
        content_type = content_type or ("text/html" if filename.lower().endswith((".html", ".htm")) else "application/pdf")
        return self._request("POST", "/v1/uploads", json={"filename": filename, "content_type": content_type, "size_bytes": size_bytes, "purpose": "document"}).json()

    def put_upload(self, upload_url: str, content: bytes, content_type: str = "application/pdf") -> None:
        # The signed URL is deliberately never logged or returned by this adapter.
        response = self.client.put(upload_url, content=content, headers={"Content-Type": content_type})
        response.raise_for_status()

    def process_upload(self, upload_id: str, session_id: str, filename: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/uploads/{upload_id}/process", json={"session_id": session_id, "filename": filename, "parse_mode": "document", "return_html": True}).json()

    def open_documents(self, session_id: str, document_ids: list[str]) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/documents/open", json={"document_ids": document_ids}).json()

    def init_session(self, session_id: str, document_ids: list[str] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"session_id": session_id}
        if document_ids:
            payload["document_ids"] = document_ids
        return self._request("POST", "/v1/sessions/init", json=payload).json()

    def session_documents(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/sessions/{session_id}/documents?include_html=true").json()

    def blank_document(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/documents/blank").json()

    def save_document(self, session_id: str, document_id: str, html: str, *, base_html: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"html": html}
        if base_html is not None: payload["base_html"] = base_html
        return self._request("POST", f"/v1/sessions/{session_id}/documents/{document_id}/save", json=payload).json()

    def documents(self) -> Any:
        return self._request("GET", "/v1/documents").json()

    def sessions(self) -> Any:
        return self._request("GET", "/v1/sessions").json()

    def chat_async(self, session_id: str, document_id: str, *, document_html: str, message: str) -> dict[str, Any]:
        if not document_id or not document_html: raise ValueError("explicit staging document_id and exact document_html are required")
        return self._request("POST", "/v1/chat/async", billable=True, json={"message": message, "document_html": document_html, "session_id": session_id, "document_id": document_id, "async_mode": True, "approval_mode": "ask_every_time", "response_mode": "compact"}).json()

    def job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/jobs/{job_id}").json()

    def session_jobs(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/sessions/{session_id}/jobs").json()

    def stream_events(self, session_id: str, job_id: str, *, last_sequence: int = 0, timeout: float = 30.0):
        """Yield each ordered SSE event once; reconnect callers pass the cursor."""
        # EventSource-compatible authentication is query-param based.  Use a
        # separate client so the normal JSON client's bearer default cannot
        # accidentally become the only stream credential.
        stream_client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=self.client._transport,
            follow_redirects=True,
            headers={"Accept": "text/event-stream"},
        )
        params = {"job_id": job_id, "api_key": self.api_key}
        if last_sequence:
            params["last_sequence"] = str(last_sequence)
        response = stream_client.stream("GET", f"/v1/chat/{session_id}/stream", params=params)
        sequence = last_sequence; seen: set[int] = set()
        event: dict[str, Any] = {}
        with response as stream:
            try:
                stream.raise_for_status()
                for line in stream.iter_lines():
                    if not line:
                        if event:
                            seq = int(event.get("sequence", sequence + 1)); event["sequence"] = seq
                            if seq not in seen and seq > last_sequence:
                                seen.add(seq); sequence = seq; yield event
                            event = {}
                        continue
                    key, _, value = line.partition(":")
                    value = value.lstrip()
                    if key == "event": event["type"] = value
                    elif key == "id": event["sequence"] = value
                    elif key == "data":
                        try:
                            parsed=json.loads(value)
                            event.update(parsed if isinstance(parsed, dict) else {"data": parsed})
                        except json.JSONDecodeError: event["data"] = value
            finally:
                stream_client.close()

    def pending_review(self, session_id: str) -> dict[str, Any]:
        jobs = self.session_jobs(session_id)
        for job in jobs.get("jobs", jobs if isinstance(jobs, list) else []):
            meta = job.get("metadata", {})
            if meta.get("pending_changes") or meta.get("pending_batch_decisions"):
                return {"job": job, "pending_changes": meta.get("pending_changes", []), "pending_batch_decisions": meta.get("pending_batch_decisions", [])}
        return {"job": None, "pending_changes": [], "pending_batch_decisions": []}

    def approve(self, session_id: str, job_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        ids = [d.get("change_id") for d in decisions]
        if not decisions or None in ids or len(ids) != len(set(ids)):
            raise ValueError("decisions must be non-empty and have unique change_id values")
        return self._request("POST", f"/v1/chat/{session_id}/approve", json={"job_id": job_id, "approved": any(d.get("approved") for d in decisions), "changes": decisions}).json()

    def detail(self, document_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/documents/{document_id}?include_html=true").json()

    def export_pdf(self, session_id: str) -> httpx.Response:
        return self._request("POST", "/v1/documents/export", json={"session_id": session_id, "format": "pdf", "options": {"filename": "linecard-m0.pdf"}})

    def export_pdf_html(self, html: str) -> httpx.Response:
        return self._request("POST", "/v1/documents/export", json={"html": html, "format": "pdf", "options": {"filename": "linecard-m1.pdf"}})


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_html(payload: Any) -> str:
    """Return only an explicit provider HTML field from a response or SSE event."""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("html") or payload.get("document_html") or payload.get("content") or "")


def response_items(payload: Any, key: str) -> list[dict[str, Any]]:
    """Normalize documented list-or-wrapper endpoint responses."""
    items = payload.get(key, []) if isinstance(payload, dict) else payload
    return items if isinstance(items, list) else []


def normalize_proposals(payload: Any) -> list[dict[str, Any]]:
    """Normalize polling/SSE and one-or-two-level JSON string proposal payloads."""
    value = payload
    for _ in range(3):
        if isinstance(value, str):
            try: value = json.loads(value)
            except json.JSONDecodeError: break
    if isinstance(value, dict):
        for key in ("proposed_change_batch", "proposed_changes", "pending_changes", "changes"):
            if key in value: value = value[key]; break
        else:
            # SuperDocs SSE wraps proposed_change_batch in a second JSON string
            # at data.content. This is documented separately from the polling
            # metadata shape and must be unwrapped before looking for changes.
            value = value.get("content", value)
    if isinstance(value, str):
        try: value = json.loads(value)
        except json.JSONDecodeError: return []
    if isinstance(value, dict) and "changes" in value:
        value = value["changes"]
    if not isinstance(value, list):
        raise ValueError("unexpected proposal shape")
    return [x if isinstance(x, dict) else json.loads(x) for x in value]


def reject_unsafe_proposals(proposals: list[dict[str, Any]], card_id: str, manual_id: str) -> None:
    for proposal in proposals:
        target = proposal.get("document_id") or proposal.get("target_document_id")
        operation = str(proposal.get("operation", "")).lower()
        if target != card_id or target == manual_id or operation in {"create_document", "delete_document"}:
            raise ValueError("proposal is not an eligible card edit")
