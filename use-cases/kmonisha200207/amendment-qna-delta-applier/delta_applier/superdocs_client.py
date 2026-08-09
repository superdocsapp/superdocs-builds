"""Thin, typed wrapper around the four SuperDocs REST calls this build needs:
upload -> chat (edit instruction, HITL) -> approve -> export.

Kept behind a small Protocol so tests can substitute a FakeSuperDocsClient
with no network access and no API key (see tests/fakes.py).

Two gotchas from the SuperDocs integration notes, handled defensively here:
  1. Some response shapes carry JSON-encoded strings that need a second
     parse (documented for the SSE `proposed_change_batch` event's `content`
     field). We poll rather than stream, but `_maybe_parse_json` guards any
     field that might arrive double-encoded regardless of transport.
  2. Large-document / deep-model-tier operations can take 30s-several
     minutes with no visible progress. `poll_job` treats "still processing"
     as normal and keeps polling up to `timeout`, never assuming a hang.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import requests


def _maybe_parse_json(value: Any) -> Any:
    """Parse `value` if it looks like a JSON-encoded string; else pass through."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in "{[":
            try:
                return json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                return value
    return value


class JobFailedError(RuntimeError):
    def __init__(self, job_id: str, error: Any):
        super().__init__(f"SuperDocs job {job_id} failed: {error}")
        self.job_id = job_id
        self.error = error


class JobTimeoutError(RuntimeError):
    def __init__(self, job_id: str, waited_seconds: float):
        super().__init__(f"SuperDocs job {job_id} did not settle within {waited_seconds:.0f}s")
        self.job_id = job_id


class SuperDocsClientProtocol(Protocol):
    def upload_document(self, file_path: str, session_id: str) -> Dict[str, Any]: ...

    def start_edit(
        self,
        session_id: str,
        message: str,
        document_html: Optional[str] = None,
        approval_mode: str = "ask_every_time",
        model_tier: Optional[str] = None,
    ) -> str: ...

    def poll_job(self, job_id: str, timeout: float = 600.0, interval: float = 2.0) -> Dict[str, Any]: ...

    def approve(
        self,
        session_id: str,
        job_id: str,
        decisions: List[Dict[str, Any]],
        default_approved: bool = True,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    def export(
        self,
        session_id: Optional[str] = None,
        html: Optional[str] = None,
        format: str = "docx",
        options: Optional[Dict[str, Any]] = None,
    ) -> bytes: ...

    def whoami(self) -> Dict[str, Any]: ...


@dataclass
class SuperDocsClient:
    api_key: str
    base_url: str = "https://api.superdocs.app"

    def _headers(self, json_body: bool = True) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def whoami(self) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/v1/agents/whoami", headers=self._headers(json_body=False))
        resp.raise_for_status()
        return resp.json()

    def upload_document(self, file_path: str, session_id: str) -> Dict[str, Any]:
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{self.base_url}/v1/documents/upload",
                headers=self._headers(json_body=False),
                files={"file": f},
                data={"session_id": session_id},
            )
        resp.raise_for_status()
        return resp.json()

    def start_edit(
        self,
        session_id: str,
        message: str,
        document_html: Optional[str] = None,
        approval_mode: str = "ask_every_time",
        model_tier: Optional[str] = None,
    ) -> str:
        body: Dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }
        if document_html is not None:
            body["document_html"] = document_html
        if model_tier is not None:
            body["model_tier"] = model_tier

        resp = requests.post(f"{self.base_url}/v1/chat/async", headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()["job_id"]

    def poll_job(self, job_id: str, timeout: float = 600.0, interval: float = 2.0) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: Dict[str, Any] = {}
        while time.monotonic() < deadline:
            resp = requests.get(f"{self.base_url}/v1/jobs/{job_id}", headers=self._headers(json_body=False))
            resp.raise_for_status()
            last = resp.json()
            status = last.get("status")

            if status == "completed":
                if "result" in last:
                    last["result"] = _maybe_parse_json(last["result"])
                return last
            if status == "failed":
                raise JobFailedError(job_id, last.get("error"))
            if status == "awaiting_approval":
                metadata = last.get("metadata") or {}
                pending = metadata.get("pending_changes")
                if pending is not None:
                    metadata["pending_changes"] = [_maybe_parse_json(c) for c in _maybe_parse_json(pending)]
                return last
            # "processing" / "queued" / anything else: keep waiting, this is
            # normal for large documents or deep model tiers, not a hang.
            time.sleep(interval)
        raise JobTimeoutError(job_id, timeout)

    def approve(
        self,
        session_id: str,
        job_id: str,
        decisions: List[Dict[str, Any]],
        default_approved: bool = True,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "job_id": job_id,
            "approved": default_approved,  # required at top level even in batch shape
            "changes": decisions,
        }
        if feedback is not None:
            body["feedback"] = feedback
        resp = requests.post(f"{self.base_url}/v1/chat/{session_id}/approve", headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()

    def export(
        self,
        session_id: Optional[str] = None,
        html: Optional[str] = None,
        format: str = "docx",
        options: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        body: Dict[str, Any] = {"format": format}
        if session_id is not None:
            body["session_id"] = session_id
        if html is not None:
            body["html"] = html
        if options is not None:
            body["options"] = options
        resp = requests.post(f"{self.base_url}/v1/documents/export", headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.content
