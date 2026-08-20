"""SuperDocs REST helper. Secrets stay in the environment, never in git."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests


class SuperDocsError(RuntimeError):
    pass


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def parse_pending_changes(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Proposed-change payloads often arrive as a JSON string and need a second parse.

    Missing that parse is why integrators see empty diff cards with every field undefined.
    """
    meta = job.get("metadata") or job.get("result") or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    raw = meta.get("pending_changes")
    if raw is None and isinstance(job.get("pending_changes"), (list, str)):
        raw = job["pending_changes"]
    return _coerce_change_list(raw)


def _coerce_change_list(raw: Any) -> list[dict[str, Any]]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
        if isinstance(raw, str):
            raw = json.loads(raw)
    if isinstance(raw, dict):
        inner = raw.get("changes") or raw.get("pending_changes") or raw.get("items")
        if inner is not None:
            return _coerce_change_list(inner)
        if "change_id" in raw or "new_html" in raw or "operation" in raw:
            raw = [raw]
        else:
            return []
    out: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, str):
            item = json.loads(item)
        if isinstance(item, dict):
            out.append(item)
    return out


class SuperDocs:
    def __init__(self, api_key: str | None = None, base: str | None = None):
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY", "")
        self.base = (base or os.environ.get("SUPERDOCS_BASE") or "https://api.superdocs.app").rstrip("/")

    def enabled(self) -> bool:
        return bool(self.api_key) and self.api_key != "your-key-here"

    def _headers(self, json_body: bool = True) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.api_key}"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _raise(self, resp: requests.Response) -> None:
        if resp.ok:
            return
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:800]
        raise SuperDocsError(f"SuperDocs {resp.status_code}: {detail}")

    def whoami(self) -> dict[str, Any]:
        r = requests.get(f"{self.base}/v1/agents/whoami", headers=self._headers(), timeout=30)
        if r.status_code == 404:
            r = requests.get(f"{self.base}/v1/users/me", headers=self._headers(), timeout=30)
        self._raise(r)
        return r.json()

    def upload_document(self, session_id: str, filename: str, data: bytes, content_type: str = "text/html") -> dict[str, Any]:
        r = requests.post(
            f"{self.base}/v1/documents/upload",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": (filename, data, content_type)},
            data={"session_id": session_id},
            timeout=120,
        )
        self._raise(r)
        return r.json()

    def upload_template(self, filename: str, data: bytes, content_type: str = "text/html") -> dict[str, Any]:
        r = requests.post(
            f"{self.base}/v1/templates/upload",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": (filename, data, content_type)},
            timeout=120,
        )
        self._raise(r)
        return r.json()

    def chat_async(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
    ) -> str:
        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "model_tier": model_tier,
        }
        if document_html is not None:
            body["document_html"] = document_html
        r = requests.post(f"{self.base}/v1/chat/async", headers=self._headers(), json=body, timeout=60)
        self._raise(r)
        data = r.json()
        job_id = data.get("job_id") or data.get("id")
        if not job_id:
            raise SuperDocsError(f"no job_id in {data}")
        return str(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        r = requests.get(f"{self.base}/v1/jobs/{job_id}", headers=self._headers(), timeout=30)
        self._raise(r)
        return r.json()

    def poll_job(self, job_id: str, timeout_s: float = 240, interval_s: float = 3) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.get_job(job_id)
            status = last.get("status")
            if status in ("completed", "failed", "cancelled", "awaiting_approval"):
                return last
            time.sleep(interval_s)
        raise SuperDocsError(f"job {job_id} still {last.get('status')} after {timeout_s}s; still processing, not a crash")

    def approve(self, session_id: str, job_id: str, decisions: dict[str, bool]) -> dict[str, Any]:
        changes = [{"change_id": cid, "approved": ok} for cid, ok in decisions.items()]
        body = {"job_id": job_id, "approved": True, "changes": changes}
        r = requests.post(
            f"{self.base}/v1/chat/{session_id}/approve",
            headers=self._headers(),
            json=body,
            timeout=60,
        )
        self._raise(r)
        return r.json() if r.content else {"ok": True}

    def continue_job(self, session_id: str, job_id: str, keep_going: bool = True) -> dict[str, Any]:
        r = requests.post(
            f"{self.base}/v1/chat/{session_id}/continue",
            headers=self._headers(),
            json={"job_id": job_id, "continue": keep_going},
            timeout=60,
        )
        self._raise(r)
        return r.json() if r.content else {"ok": True}

    def export(self, session_id: str | None = None, html: str | None = None, fmt: str = "docx", filename: str = "export") -> bytes:
        body: dict[str, Any] = {"format": fmt, "options": {"filename": filename}}
        if session_id:
            body["session_id"] = session_id
        if html is not None:
            body["html"] = html
        r = requests.post(f"{self.base}/v1/documents/export", headers=self._headers(), json=body, timeout=120)
        self._raise(r)
        return r.content
