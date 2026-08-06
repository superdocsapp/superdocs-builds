"""Thin client for the SuperDocs REST API.

Covers the four-call contract the build needs: upload a document, send an
edit instruction, approve the proposed changes, and export the finished file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

BASE_URL = "https://api.superdocs.app"

POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 600
APPROVAL_TIMEOUT_SECONDS = 3600


class SuperDocsError(RuntimeError):
    """Raised when the SuperDocs API returns an error we cannot recover from."""


@dataclass
class ProposedChange:
    change_id: str
    operation: str
    chunk_id: Optional[str]
    old_html: Optional[str]
    new_html: Optional[str]
    ai_explanation: str
    insert_after_chunk_id: Optional[str] = None


@dataclass
class EditResult:
    response: str
    updated_html: Optional[str]
    changes: list[ProposedChange] = field(default_factory=list)


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: int = 60) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {api_key}"})

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _raise_for_status(self, response: requests.Response) -> None:
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("detail") or response.json().get("error") or ""
            except ValueError:
                detail = response.text[:300]
            raise SuperDocsError(
                f"SuperDocs API {response.status_code} on {response.url}: {detail}"
            )

    def upload_document(self, file_path: str, session_id: str) -> dict[str, Any]:
        """Upload a file as the active editable document of a session."""
        with open(file_path, "rb") as fh:
            response = self._session.post(
                self._url("/v1/documents/upload"),
                files={"file": fh},
                data={"session_id": session_id},
                timeout=self._timeout,
            )
        self._raise_for_status(response)
        return response.json()

    def start_edit(
        self,
        session_id: str,
        message: str,
        document_html: str,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
    ) -> str:
        """Start an async edit and return the job id."""
        response = self._session.post(
            self._url("/v1/chat/async"),
            json={
                "message": message,
                "session_id": session_id,
                "document_html": document_html,
                "approval_mode": approval_mode,
                "model_tier": model_tier,
            },
            timeout=self._timeout,
        )
        self._raise_for_status(response)
        return response.json()["job_id"]

    def get_job(self, job_id: str) -> dict[str, Any]:
        response = self._session.get(self._url(f"/v1/jobs/{job_id}"), timeout=self._timeout)
        self._raise_for_status(response)
        return response.json()

    def approve_changes(
        self,
        session_id: str,
        job_id: str,
        decisions: list[tuple[str, bool]],
    ) -> None:
        """Approve or deny proposed changes. Each tuple is (change_id, approved)."""
        response = self._session.post(
            self._url(f"/v1/chat/{session_id}/approve"),
            json={
                "job_id": job_id,
                "approved": True,
                "changes": [
                    {"change_id": change_id, "approved": approved}
                    for change_id, approved in decisions
                ],
            },
            timeout=self._timeout,
        )
        self._raise_for_status(response)

    def export_document(self, session_id: str, format: str = "markdown") -> bytes:
        response = self._session.post(
            self._url("/v1/documents/export"),
            json={"session_id": session_id, "format": format},
            timeout=self._timeout,
        )
        self._raise_for_status(response)
        return response.content

    def wait_for_edit(
        self,
        session_id: str,
        job_id: str,
        approve: bool = True,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        poll_timeout: float = POLL_TIMEOUT_SECONDS,
        approval_timeout: float = APPROVAL_TIMEOUT_SECONDS,
    ) -> EditResult:
        """Poll a job to completion, approving (or denying) any proposed changes.

        The job can pause in ``awaiting_approval`` for two reasons; we branch on
        ``metadata.awaiting_kind`` exactly as the docs require:
        - ``continue_prompt``: a large edit paused. No pending changes; resume
          with /continue.
        - anything else: a HITL change review. Read ``pending_changes`` and
          respond via /approve.
        """
        deadline = time.monotonic() + poll_timeout
        approval_deadline: Optional[float] = None

        while True:
            if time.monotonic() > deadline:
                raise SuperDocsError(f"Timed out waiting for job {job_id}")

            job = self.get_job(job_id)
            status = job["status"]

            if status == "completed":
                result = job["result"]
                changes = self._parse_changes(job.get("metadata", {}))
                if not changes:
                    print(
                        "[docs-pr] note: job completed with no proposed changes; "
                        f"AI response: {result.get('response', '')[:300]!r}"
                    )
                return EditResult(
                    response=result.get("response", ""),
                    updated_html=(
                        result.get("document_changes", {}).get("updated_html")
                        if result.get("document_changes")
                        else None
                    ),
                    changes=changes,
                )

            if status == "failed":
                raise SuperDocsError(f"Job {job_id} failed: {job.get('error')}")

            if status == "awaiting_approval":
                metadata = job.get("metadata", {})
                awaiting_kind = metadata.get("awaiting_kind")

                if awaiting_kind == "continue_prompt":
                    self._continue_job(session_id, job_id, continue_edit=True)
                    continue

                changes = self._parse_changes(metadata)
                if not changes:
                    raise SuperDocsError(
                        f"Job {job_id} is awaiting_approval but carries no pending changes"
                    )

                if approval_deadline is None:
                    approval_deadline = time.monotonic() + approval_timeout
                if time.monotonic() > approval_deadline:
                    raise SuperDocsError(
                        f"Job {job_id} waited too long for approval; "
                        "the server auto-denies unattended reviews after about an hour"
                    )

                decisions = [(c.change_id, approve) for c in changes]
                self.approve_changes(session_id, job_id, decisions)
                continue

            time.sleep(poll_interval)

    def _continue_job(self, session_id: str, job_id: str, continue_edit: bool) -> None:
        response = self._session.post(
            self._url(f"/v1/chat/{session_id}/continue"),
            json={"job_id": job_id, "continue": continue_edit},
            timeout=self._timeout,
        )
        self._raise_for_status(response)

    @staticmethod
    def _parse_changes(metadata: dict[str, Any]) -> list[ProposedChange]:
        """Parse pending changes, tolerating the JSON-encoded-string gotcha.

        Proposed-change content can arrive as a JSON-encoded string and needs a
        second parse; the final result is already an object. We accept both.
        A completed job may carry no pending changes at all (None or missing).
        """
        if not metadata:
            return []
        raw = metadata.get("pending_changes")
        if raw is None:
            return []
        if isinstance(raw, str):
            import json

            raw = json.loads(raw)
        changes: list[ProposedChange] = []
        for entry in raw:
            if isinstance(entry, str):
                import json

                entry = json.loads(entry)
            changes.append(
                ProposedChange(
                    change_id=entry["change_id"],
                    operation=entry.get("operation", "edit"),
                    chunk_id=entry.get("chunk_id"),
                    old_html=entry.get("old_html"),
                    new_html=entry.get("new_html"),
                    ai_explanation=entry.get("ai_explanation", ""),
                    insert_after_chunk_id=entry.get("insert_after_chunk_id"),
                )
            )
        return changes
