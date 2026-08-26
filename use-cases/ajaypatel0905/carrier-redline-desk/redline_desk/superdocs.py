"""Thin SuperDocs REST client.

The transport is injectable so the whole pipeline can run against recorded
fixtures in tests, with no live key and no network.
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests

BASE_URL = "https://api.superdocs.app/v1"

Transport = Callable[..., requests.Response]


class SuperDocsError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class UsageLedger:
    """Accumulates the usage block of every billable response, keyed by stage."""

    entries: list[dict] = field(default_factory=list)

    def record(self, stage: str, usage: Optional[dict]) -> None:
        if usage:
            self.entries.append({"stage": stage, "ops_charged": usage.get("ops_charged", 1 if usage.get("was_billable") else 0), "usage": usage})

    def ops_by_stage(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for e in self.entries:
            totals[e["stage"]] = totals.get(e["stage"], 0) + (e["ops_charged"] or 0)
        return totals

    def total_ops(self) -> int:
        return sum(self.ops_by_stage().values())


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, transport: Optional[Transport] = None, ledger: Optional[UsageLedger] = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._transport = transport or self._http
        self.ledger = ledger or UsageLedger()

    def _http(self, method: str, path: str, **kwargs) -> requests.Response:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.api_key}"
        return requests.request(method, f"{self.base_url}{path}", headers=headers, timeout=kwargs.pop("timeout", 300), **kwargs)

    def _call(self, method: str, path: str, **kwargs) -> requests.Response:
        resp = self._transport(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text[:500]
            raise SuperDocsError(f"{method} {path} -> HTTP {resp.status_code}: {body}", resp.status_code, body)
        return resp

    def upload_document(self, path: str | pathlib.Path, session_id: str, stage: str = "parse") -> dict:
        path = pathlib.Path(path)
        with path.open("rb") as f:
            resp = self._call("POST", "/documents/upload", files={"file": (path.name, f)}, data={"session_id": session_id})
        return resp.json()

    def chat_async(self, session_id: str, message: str, *, approval_mode: Optional[str] = None, document_html: Optional[str] = None, model_tier: Optional[str] = None, stage: str = "evaluate") -> str:
        payload: dict[str, Any] = {"session_id": session_id, "message": message}
        if approval_mode:
            payload["approval_mode"] = approval_mode
        if document_html is not None:
            payload["document_html"] = document_html
        if model_tier:
            payload["model_tier"] = model_tier
        body = self._call("POST", "/chat/async", json=payload).json()
        self.ledger.record(stage, body.get("usage"))
        return body["job_id"]

    def get_job(self, job_id: str) -> dict:
        return self._call("GET", f"/jobs/{job_id}").json()

    def wait_for_job(self, job_id: str, *, poll_seconds: float = 1.5, timeout_seconds: float = 1800.0, on_poll: Optional[Callable[[dict], None]] = None) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while True:
            job = self.get_job(job_id)
            if on_poll:
                on_poll(job)
            if job["status"] not in ("pending", "in_progress"):
                return job
            if time.monotonic() > deadline:
                raise SuperDocsError(f"job {job_id} still {job['status']} after {timeout_seconds}s")
            time.sleep(poll_seconds)

    def approve(self, session_id: str, job_id: str, decisions: list[dict], feedback: Optional[str] = None) -> dict:
        payload: dict[str, Any] = {"job_id": job_id}
        if len(decisions) == 1 and not feedback:
            payload.update({"change_id": decisions[0]["change_id"], "approved": decisions[0]["approved"]})
            if decisions[0].get("feedback"):
                payload["feedback"] = decisions[0]["feedback"]
        else:
            payload["approved"] = all(d["approved"] for d in decisions)
            payload["changes"] = [{"change_id": d["change_id"], "approved": d["approved"]} for d in decisions]
            if feedback:
                payload["feedback"] = feedback
        return self._call("POST", f"/chat/{session_id}/approve", json=payload).json()

    def export_docx(self, *, html: Optional[str] = None, session_id: Optional[str] = None, options: Optional[dict] = None) -> tuple[bytes, Optional[str]]:
        payload: dict[str, Any] = {"format": "docx"}
        if html is not None:
            payload["html"] = html
        if session_id is not None:
            payload["session_id"] = session_id
        if options:
            payload["options"] = options
        resp = self._call("POST", "/documents/export", json=payload)
        return resp.content, resp.headers.get("X-Export-Warnings")

    def record_job_usage(self, stage: str, job: dict) -> None:
        """Usage rides the terminal job at result.usage (the async-chat response
        itself carries none, docs notwithstanding). Call once per finished job."""
        if job.get("status") in ("completed", "failed", "cancelled"):
            usage = (job.get("result") or {}).get("usage")
            if usage:
                usage = dict(usage, cumulative_tokens=(job.get("metadata") or {}).get("cumulative_tokens"))
            self.ledger.record(stage, usage)

    @staticmethod
    def pending_changes(job: dict) -> list[dict]:
        pc = (job.get("metadata") or {}).get("pending_changes") or []
        if isinstance(pc, str):  # SSE-path payloads arrive JSON-encoded; tolerate it here too
            pc = json.loads(pc)
        return pc
