from __future__ import annotations

import html
import os
import time
import uuid
from pathlib import Path
from typing import Callable

import httpx

from .models import EditProposal


class SuperDocsClient:
    """Thin server-side client; the API key never crosses a browser boundary."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, transport=None) -> None:
        self.api_key = api_key or os.getenv("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise ValueError("SUPERDOCS_API_KEY is required for live mode; preview mode never needs it")
        self.client = httpx.Client(
            base_url=base_url or os.getenv("SUPERDOCS_BASE_URL", "https://api.superdocs.app"),
            headers={"Authorization": f"Bearer {self.api_key}"}, timeout=120, transport=transport,
        )

    @staticmethod
    def markdown_html(text: str) -> str:
        return "\n".join(f'<p data-chunk-id="line-{index}">{html.escape(line)}</p>' for index, line in enumerate(text.splitlines(), 1))

    def propose(self, path: Path, proposal: EditProposal, decide: Callable[[dict], tuple[bool, str]], poll_seconds: float = 1.0) -> dict:
        session_id = f"spec-sync-{uuid.uuid4()}"
        instruction = (
            f"Apply only this approved documentation intent: {proposal.rationale}. "
            f"Target `{proposal.needle}` and use `{proposal.replacement}` where supplied. "
            "Do not alter unrelated sections. If the instruction is uncertain, propose no edit and explain why."
        )
        response = self.client.post(
            "/v1/chat/async",
            json={"message": instruction, "session_id": session_id, "document_html": self.markdown_html(path.read_text(encoding="utf-8")), "approval_mode": "ask_every_time", "response_mode": "compact"},
        )
        response.raise_for_status()
        job_id = response.json()["job_id"]
        while True:
            job = self.client.get(f"/v1/jobs/{job_id}")
            job.raise_for_status()
            payload = job.json()
            status = payload["status"]
            if status == "awaiting_approval":
                changes = payload.get("metadata", {}).get("pending_changes", [])
                decisions = []
                for change in changes:
                    approved, feedback = decide(change)
                    decisions.append({"change_id": change["change_id"], "approved": approved, "feedback": feedback})
                approved = self.client.post(f"/v1/chat/{session_id}/approve", json={"job_id": job_id, "approved": True, "changes": decisions})
                approved.raise_for_status()
            elif status == "completed":
                payload["session_id"] = session_id
                return payload
            elif status in {"failed", "cancelled"}:
                raise RuntimeError(f"SuperDocs job {status}: {payload}")
            time.sleep(poll_seconds)

    def export(self, session_id: str, filename: str, format: str = "docx") -> bytes:
        response = self.client.post(
            "/v1/documents/export",
            json={"session_id": session_id, "format": format, "filename": filename},
        )
        response.raise_for_status()
        return response.content
