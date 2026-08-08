"""Thin SuperDocs client for the appeal flow.

Four calls: upload, edit with approval required, approve, export. Written directly against the
REST API rather than pulled from a package, so this app stays a readable example of the
contract rather than a demonstration of a dependency.

Three things learned against the live API and encoded here so they do not have to be
rediscovered:

  * The upload field is `file_base64`, not `content_base64`.
  * A large edit arrives in SEVERAL approval rounds; the job returns to `awaiting_approval`
    after each. Approving once and waiting for completion polls forever.
  * A job stuck in `awaiting_approval` cannot be cancelled — `cancel_job` returns 400 — so a
    wedged session is cleared by DENYING its pending changes.
"""

from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app")
TERMINAL = {"completed", "failed", "cancelled"}


class SuperDocsError(RuntimeError):
    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body

    @property
    def is_session_busy(self) -> bool:
        return "session_busy" in self.body


@dataclass(frozen=True, slots=True)
class ProposedChange:
    change_id: str
    operation: str
    old_html: str
    new_html: str
    explanation: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> ProposedChange:
        return cls(
            change_id=raw.get("change_id", ""),
            operation=raw.get("operation", "edit"),
            # NOT double-parsed. On the polling path these are real strings; the second parse
            # the docs describe applies to the SSE/intermediate_responses path only.
            old_html=raw.get("old_html") or "",
            new_html=raw.get("new_html") or "",
            explanation=raw.get("ai_explanation") or "",
        )


class SuperDocs:
    def __init__(self, api_key: str | None = None, *, timeout: float = 300.0):
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY", "")
        if not self.api_key:
            raise SuperDocsError(
                "SUPERDOCS_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "payer-appeals/0.1",
        }

    async def _post(self, client: httpx.AsyncClient, path: str, body: dict[str, Any]) -> Any:
        response = await client.post(BASE_URL + path, json=body, headers=self._headers())
        if response.status_code >= 400:
            raise SuperDocsError(
                f"POST {path} -> {response.status_code}: {response.text[:400]}",
                response.status_code,
                response.text,
            )
        return response.json()

    async def _get(self, client: httpx.AsyncClient, path: str) -> Any:
        response = await client.get(BASE_URL + path, headers=self._headers())
        if response.status_code >= 400:
            raise SuperDocsError(
                f"GET {path} -> {response.status_code}: {response.text[:400]}",
                response.status_code,
                response.text,
            )
        return response.json()

    # ------------------------------------------------------------------------------

    async def upload(self, session_id: str, filename: str, content: bytes) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await self._post(
                client,
                "/v1/documents/upload-base64",
                {
                    "filename": filename,
                    # `file_base64`. Not `content_base64` — that returns a 422 whose message
                    # is the only place the right name appears.
                    "file_base64": base64.b64encode(content).decode(),
                    "session_id": session_id,
                    "return_html": True,
                },
            )

    async def start_edit(self, session_id: str, instruction: str, document_html: str | None = None):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            body: dict[str, Any] = {
                "message": instruction,
                "session_id": session_id,
                "approval_mode": "ask_every_time",
            }
            if document_html:
                body["document_html"] = document_html
            return await self._post(client, "/v1/chat/async", body)

    async def get_job(self, job_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await self._get(client, f"/v1/jobs/{job_id}")

    async def wait_for_review(self, job_id: str, *, poll: float = 2.0, limit: int = 150):
        """Poll until the job wants a decision or finishes.

        `limit` is a real bound rather than a formality: without one, a job that never reaches
        a terminal state polls forever, which is exactly what happened before the multi-round
        behaviour was understood.
        """
        for _ in range(limit):
            job = await self.get_job(job_id)
            status = job.get("status", "")
            if status == "awaiting_approval" or status in TERMINAL:
                return job
            await asyncio.sleep(poll)
        raise SuperDocsError(f"job {job_id} never settled after {limit} polls")

    async def decide(self, session_id: str, job_id: str, decisions: list[dict[str, Any]]):
        """Approve/reject each change. `decisions` is [{change_id, approved, feedback}]."""
        if not decisions:
            raise SuperDocsError("no decisions supplied; refusing to guess")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await self._post(
                client,
                f"/v1/chat/{session_id}/approve",
                {
                    "job_id": job_id,
                    # Required even for batch decisions. Omitting it is a 422 that does not
                    # say which field is missing.
                    "approved": True,
                    "changes": decisions,
                },
            )

    async def export(self, session_id: str, fmt: str = "docx") -> tuple[bytes, str, str]:
        """Returns (bytes, filename, content_type). Exports do not consume operations."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                BASE_URL + "/v1/documents/export",
                json={"session_id": session_id, "format": fmt},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if response.status_code >= 400:
                raise SuperDocsError(
                    f"export -> {response.status_code}: {response.text[:300]}",
                    response.status_code,
                    response.text,
                )
            disposition = response.headers.get("content-disposition", "")
            filename = f"appeal.{fmt}"
            if "filename=" in disposition:
                filename = disposition.split("filename=")[1].split(";")[0].strip('"')
            return (
                response.content,
                filename,
                response.headers.get("content-type", "application/octet-stream"),
            )

    async def clear_wedged_session(self, session_id: str) -> int:
        """Free a session whose previous job was abandoned mid-review.

        Denies rather than cancels: `cancel_job` returns 400 "Job cannot be cancelled" on an
        `awaiting_approval` job, even though the 409's own suggested_action recommends it.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = await self._get(client, f"/v1/sessions/{session_id}/jobs")
        cleared = 0
        for job in payload.get("jobs") or []:
            if job.get("status") in TERMINAL:
                continue
            pending = (job.get("metadata") or {}).get("pending_changes") or []
            if not pending:
                continue
            await self.decide(
                session_id,
                job["job_id"],
                [
                    {"change_id": c["change_id"], "approved": False,
                     "feedback": "abandoned by a previous session"}
                    for c in pending
                ],
            )
            cleared += 1
        return cleared
