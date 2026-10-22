"""
Thin wrapper over the SuperDocs REST API. Every method here maps to exactly
one call documented in docs/superdocs-api-reference.md — if you're adding a
call that isn't in that reference, check the real docs first, don't guess
the shape.

The one thing every integrator reportedly gets wrong (per the SuperDocs
brief itself): proposed-change content in pending_changes arrives as a
JSON-encoded STRING, not a nested object — needs a second json.loads. See
_parse_pending_changes below; every caller goes through it, not raw access.

Live-verified 2026-08-12 (see PROGRESS.md): two methods diverged from the
documented shape and were fixed here — approve_change (the docs' batch
{"changes":[...]} payload 422s; the real endpoint takes one job_id +
change_id + approved decision per call) and get_session_jobs (the real
response is {"jobs": [...], "total": N}, unwrapped here).
"""

import base64
import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class SuperDocsClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.superdocs_api_key
        self.base_url = base_url or settings.superdocs_base_url
        self._headers = {"Authorization": f"Bearer {self.api_key}"}

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, headers=self._headers, timeout=60.0)

    def upload_document(self, session_id: str, filename: str, content: bytes) -> dict:
        """Loads a file as the session's active EDITABLE document."""
        with self._client() as c:
            r = c.post(
                "/v1/documents/upload-base64",
                json={
                    "session_id": session_id,
                    "filename": filename,
                    "file_base64": base64.b64encode(content).decode(),
                },
            )
            r.raise_for_status()
            return r.json()

    def upload_attachment(self, session_id: str, filename: str, content: bytes) -> dict:
        """Loads a file as READ-ONLY reference context, never the edit target."""
        with self._client() as c:
            r = c.post(
                "/v1/attachments/upload-base64",
                json={
                    "session_id": session_id,
                    "filename": filename,
                    "file_base64": base64.b64encode(content).decode(),
                },
            )
            r.raise_for_status()
            return r.json()  # returns job_id — caller polls get_job

    def start_round(self, session_id: str, message: str) -> dict:
        """Starts a HITL redline round. Returns immediately with a job_id."""
        with self._client() as c:
            r = c.post(
                "/v1/chat/async",
                json={
                    "session_id": session_id,
                    "message": message,
                    "approval_mode": "ask_every_time",
                },
            )
            r.raise_for_status()
            return r.json()

    def get_job(self, job_id: str) -> dict:
        with self._client() as c:
            r = c.get(f"/v1/jobs/{job_id}")
            r.raise_for_status()
            return r.json()

    def approve_change(
        self, session_id: str, job_id: str, change_id: str, approved: bool, feedback: str | None = None
    ) -> dict:
        """Approves/denies ONE proposed change. docs/superdocs-api-reference.md
        describes a batch {"changes": [...]} payload — confirmed live 2026-08-12
        that this 422s (job_id and approved are required top-level fields).
        The real endpoint takes one decision per call: job_id + change_id
        (the per-proposal id from pending_changes, NOT chunk_id — a
        chunk_id-keyed call is silently ignored) + approved, and returns
        {"status", "message", "batch_complete"}; batch_complete is true once
        every pending_changes entry on that job has been decided."""
        payload: dict = {"job_id": job_id, "approved": approved, "change_id": change_id}
        if feedback is not None:
            payload["feedback"] = feedback
        with self._client() as c:
            r = c.post(f"/v1/chat/{session_id}/approve", json=payload)
            r.raise_for_status()
            return r.json()

    def get_session_jobs(self, session_id: str) -> list[dict]:
        """The durable audit trail the open-items tracker reconciles against.
        Confirmed live 2026-08-12: the real response is {"jobs": [...],
        "total": N}, not a bare list — unwrapped here so every caller gets
        a plain list, matching this method's documented return type."""
        with self._client() as c:
            r = c.get(f"/v1/sessions/{session_id}/jobs")
            r.raise_for_status()
            data = r.json()
            return data.get("jobs", []) if isinstance(data, dict) else data

    def export(self, session_id: str, format: str = "docx") -> bytes:
        with self._client() as c:
            r = c.post("/v1/documents/export", json={"session_id": session_id, "format": format})
            r.raise_for_status()
            return r.content

    @staticmethod
    def parse_pending_changes(job_response: dict) -> list[dict]:
        """
        The documented gotcha: metadata.pending_changes entries carry their
        diff content as a JSON-ENCODED STRING, not a nested object. This is
        the single place that unwraps it — every caller uses this, never
        reads job_response["metadata"]["pending_changes"] directly.
        """
        # metadata.pending_changes is null (not just missing) while a round
        # is still in_progress, per a live response observed 2026-08-12 —
        # .get(key, []) doesn't cover key: null, only key missing entirely
        metadata = job_response.get("metadata") or {}
        raw = metadata.get("pending_changes") or []
        parsed = []
        for change in raw:
            content = change.get("content") or change.get("diff") or change.get("html")
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    pass  # some fields are legitimately plain strings — don't force it
            parsed.append({**change, "content": content})
        return parsed
