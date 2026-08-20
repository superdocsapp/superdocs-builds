"""Thin SuperDocs REST client: the four minimum-contract calls plus polling and usage.

upload   -> POST /v1/documents/upload-base64
chat     -> POST /v1/chat/async            (ask_every_time -> job pauses for approval)
approve  -> POST /v1/chat/{session_id}/approve
export   -> POST /v1/documents/export
"""

import base64
import json
import time
from typing import Any, Optional

import requests

from . import config
from .budget import BudgetGuard


class SuperDocsError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class SuperDocsClient:
    def __init__(self, api_key: Optional[str] = None, budget: Optional[BudgetGuard] = None):
        self.api_key = api_key or config.require_key()
        self.base = config.API_BASE
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})
        self.budget = budget or BudgetGuard()

    def _request(self, method: str, path: str, json_body: Optional[dict] = None, timeout: int = 300) -> Any:
        url = f"{self.base}{path}"
        try:
            resp = self.session.request(method, url, json=json_body, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            raise SuperDocsError(f"request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise SuperDocsError(
                f"{method} {path} -> {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
                body=resp.text,
            )
        if not resp.content:
            return None
        return resp.json()

    def whoami(self) -> dict:
        return self._request("GET", "/v1/agents/whoami")

    def upload_base64(self, filename: str, file_bytes: bytes, session_id: str, return_html: bool = False) -> dict:
        body = {
            "filename": filename,
            "file_base64": base64.b64encode(file_bytes).decode(),
            "session_id": session_id,
            "return_html": return_html,
        }
        return self._request("POST", "/v1/documents/upload-base64", body, timeout=300)

    def chat_sync(self, session_id: str, message: str, approval_mode: str = "ask_every_time",
                  model_tier: Optional[str] = None, thinking_depth: Optional[str] = None) -> dict:
        """Synchronous chat turn. Used by the automated judge (analysis-only)."""
        body = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "model_tier": model_tier or config.MODEL_TIER,
            "thinking_depth": thinking_depth or config.THINKING_DEPTH,
        }
        self.budget.guard(1)
        resp = self._request("POST", "/v1/chat", body, timeout=300)
        self.budget.record(resp, endpoint="/v1/chat", tag=f"chat_sync:{session_id}")
        return resp

    def chat_async(self, session_id: str, message: str, approval_mode: str = "ask_every_time",
                   model_tier: Optional[str] = None, thinking_depth: Optional[str] = None) -> dict:
        """Start an async edit. Returns {job_id, session_id, usage?...}. Bills ops."""
        body = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "model_tier": model_tier or config.MODEL_TIER,
            "thinking_depth": thinking_depth or config.THINKING_DEPTH,
        }
        self.budget.guard(1)
        resp = self._request("POST", "/v1/chat/async", body, timeout=300)
        self.budget.record(resp)
        return resp

    def get_job(self, job_id: str) -> dict:
        return self._request("GET", f"/v1/jobs/{job_id}", timeout=120)

    def poll_job(self, job_id: str, timeout_s: int = 600, interval_s: float = 5.0) -> dict:
        """Poll a job to completion or awaiting_approval. Long generations are normal."""
        deadline = time.monotonic() + timeout_s
        last = None
        while time.monotonic() < deadline:
            last = self.get_job(job_id)
            if last.get("status") in ("completed", "failed", "cancelled", "awaiting_approval"):
                return last
            time.sleep(interval_s)
        raise SuperDocsError(f"job {job_id} still {last and last.get('status')} after {timeout_s}s")

    def approve(self, session_id: str, job_id: str, approved: bool = True,
                changes: Optional[list] = None, feedback: Optional[str] = None) -> dict:
        body = {"job_id": job_id, "approved": approved}
        if feedback is not None:
            body["feedback"] = feedback
        if changes is not None:
            body["changes"] = changes
        return self._request("POST", f"/v1/chat/{session_id}/approve", body, timeout=120)

    def export(self, session_id: Optional[str] = None, html: Optional[str] = None,
               fmt: str = "docx", filename: Optional[str] = None) -> bytes:
        """Export is not a billable operation."""
        body: dict = {"format": fmt}
        if session_id:
            body["session_id"] = session_id
        if html is not None:
            body["html"] = html
        if filename:
            body["options"] = {"filename": filename}
        resp = self.session.post(
            f"{self.base}/v1/documents/export", json=body, headers=self.session.headers, timeout=300
        )
        if resp.status_code >= 400:
            raise SuperDocsError(
                f"export -> {resp.status_code}: {resp.text[:500]}", status_code=resp.status_code
            )
        return resp.content

    def session_documents(self, session_id: str, include_html: bool = False) -> dict:
        return self._request(
            "GET", f"/v1/sessions/{session_id}/documents?include_html={'true' if include_html else 'false'}",
            timeout=120,
        )

    def account_status(self) -> dict:
        return self._request("GET", "/v1/agents/whoami", timeout=60)


def parse_usage(resp: dict) -> dict:
    """Usage may appear top-level or nested; returns a normalized dict."""
    usage = resp.get("usage") if isinstance(resp, dict) else None
    if usage is None and isinstance(resp, dict):
        for key in ("quota", "account"):
            if isinstance(resp.get(key), dict):
                usage = resp[key]
                break
    if not isinstance(usage, dict):
        return {"was_billable": False, "ops_charged": 0}
    return {
        "was_billable": bool(usage.get("was_billable", False)),
        "ops_charged": int(usage.get("ops_charged", 0) or 0),
        "monthly_remaining": usage.get("monthly_remaining"),
        "monthly_used": usage.get("monthly_used"),
    }


def extract_json_from_text(text: str) -> Optional[dict]:
    """SuperDocs sometimes wraps structured payloads as a JSON-encoded string;
    this does the second parse integrators keep missing."""
    text = (text or "").strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None