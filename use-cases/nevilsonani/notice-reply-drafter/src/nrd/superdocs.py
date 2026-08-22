"""Thin SuperDocs client with an operation budget and honest errors.

Same battle-tested core as my site-survey build (warmup retry, job polling,
second-parse of pending changes, budget hard-stop), extended with the
templates surface: upload once, and the drafting chat finds it by search.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

API = "https://api.superdocs.app"


class BudgetExceeded(RuntimeError):
    pass


class SuperDocsError(RuntimeError):
    def __init__(self, what: str, status: int, body: str):
        super().__init__(f"{what} failed with HTTP {status}: {body[:300]}")
        self.status = status


class OpBudget:
    def __init__(self, max_ops: int):
        self.max_ops = max_ops
        self.used = 0

    def precheck(self) -> None:
        if self.used >= self.max_ops:
            raise BudgetExceeded(
                f"op budget reached ({self.used}/{self.max_ops}); "
                "raise NRD_OP_BUDGET to continue"
            )

    def charge(self, usage: dict | None) -> None:
        if usage and usage.get("was_billable"):
            self.used += int(usage.get("ops_charged", 1))


def _second_parse(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class SuperDocs:
    def __init__(self, api_key: str | None = None, budget: int | None = None):
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY", "")
        if not self.api_key:
            raise SystemExit("no API key: set SUPERDOCS_API_KEY (see .env.example)")
        self.budget = OpBudget(budget or int(os.environ.get("NRD_OP_BUDGET", "15")))
        self.http = httpx.Client(
            base_url=API,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(300.0, connect=30.0),
        )
        self._charged_jobs: set[str] = set()

    def _request(self, method: str, path: str, *, what: str, retries: int = 1, **kw):
        for attempt in range(retries + 1):
            r = self.http.request(method, path, **kw)
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code >= 500 and attempt < retries:
                time.sleep(3)  # fresh-session warmup, per the docs
                continue
            if r.status_code >= 400:
                raise SuperDocsError(what, r.status_code, r.text)
            return r
        raise SuperDocsError(what, r.status_code, r.text)

    # -------------------------------------------------------- templates

    def ensure_template(self, path: Path) -> dict:
        """Upload the firm template once; skip if one with this name exists."""
        r = self._request("GET", "/v1/templates", what="list templates")
        body = r.json()
        existing = body.get("templates", body if isinstance(body, list) else [])
        for t in existing:
            name = t.get("name") or t.get("filename") or ""
            if path.stem in name or path.name == name:
                return {"skipped": True, "template": t}
        with path.open("rb") as fh:
            r = self._request("POST", "/v1/templates/upload",
                              what=f"upload template {path.name}",
                              files={"file": (path.name, fh)})
        return {"skipped": False, "template": r.json()}

    # ------------------------------------------------------------- chat

    def chat_async(self, session_id: str, message: str,
                   document_html: str | None = None,
                   approval_mode: str = "ask_every_time") -> str:
        self.budget.precheck()
        payload: dict = {"message": message, "session_id": session_id,
                         "approval_mode": approval_mode}
        if document_html is not None:
            payload["document_html"] = document_html
        r = self._request("POST", "/v1/chat/async", what="chat/async", json=payload)
        body = r.json()
        job_id = body.get("job_id") or body.get("id")
        if not job_id:
            raise SuperDocsError("chat/async", r.status_code,
                                 f"no job_id in response: {json.dumps(body)[:200]}")
        return job_id

    def wait_job(self, job_id: str, timeout_s: int = 900, poll_s: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout_s
        while True:
            r = self._request("GET", f"/v1/jobs/{job_id}", what="job status")
            job = r.json()
            status = job.get("status")
            if status not in ("pending", "in_progress", "queued", "running"):
                usage = job.get("usage") or (job.get("result") or {}).get("usage") \
                    or (job.get("metadata") or {}).get("usage")
                if usage and job_id not in self._charged_jobs:
                    self.budget.charge(usage)
                    self._charged_jobs.add(job_id)
                meta = job.get("metadata") or {}
                meta["pending_changes"] = _second_parse(meta.get("pending_changes"))
                job["metadata"] = meta
                return job
            if time.monotonic() > deadline:
                raise TimeoutError(f"job {job_id} still {status} after {timeout_s}s")
            time.sleep(poll_s)

    def approve(self, session_id: str, job_id: str,
                decisions: list[dict], default_approved: bool = True) -> dict:
        payload = {"job_id": job_id, "approved": default_approved,
                   "changes": decisions}
        r = self._request("POST", f"/v1/chat/{session_id}/approve",
                          what="approve", json=payload)
        return r.json()

    # ------------------------------------------------------ attachments

    def upload_attachment(self, session_id: str, path: Path) -> dict:
        import base64

        self.budget.precheck()
        payload = {
            "filename": path.name,
            "file_base64": base64.b64encode(path.read_bytes()).decode(),
            "session_id": session_id,
            "return_html": True,
        }
        r = self._request("POST", "/v1/attachments/upload-base64",
                          what=f"upload {path.name}", json=payload)
        body = r.json()
        self.budget.charge(body.get("usage"))
        return body

    # ----------------------------------------------------------- export

    def export(self, session_id: str, fmt: str = "docx") -> bytes:
        r = self._request("POST", "/v1/documents/export", what=f"export {fmt}",
                          json={"session_id": session_id, "format": fmt})
        return r.content
