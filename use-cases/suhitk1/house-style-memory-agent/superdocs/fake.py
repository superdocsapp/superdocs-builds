"""A deliberately-designed fake SuperDocs transport.

Rebuilt on 2026-08-13 from responses captured off the live service
(tests/fixtures/real_responses/). The previous version was written from the
brief and shared the client's wrong shapes, so the keyless suite passed while
the client could not have worked against the real API. That is precisely Task
1's lesson: a fake that agrees with your assumptions tests nothing.

Awkward parts reproduced on purpose, each observed live:

- `chat` returns `document_changes` as a dict (updated_html, requires_approval,
  pending_changes), NOT a `proposed_changes` list.
- `usage` reports the service's own charge, and a chat that changes nothing is
  billed 0 — billing follows the edit, not the call.
- `init_session` rejects an empty argument object (HTTP 422): `document_ids`
  must be present even when empty.
- `approve_change` with only a job_id returns `batch_complete: false` and
  applies NOTHING. Only per-`change_id` approval completes the batch.
- Async jobs pass through `in_progress` before reaching `awaiting_approval`.
- Errors come back as an `{"error": ...}` envelope rather than as exceptions.

Anything this fake makes easier than reality is a bug in the fake.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

OXFORD_BEFORE = "The team reviewed scope, budget and timeline."
OXFORD_AFTER = "The team reviewed scope, budget, and timeline."


@dataclass
class FakeSuperDocs:
    """In-memory stand-in. No network, no key."""

    sessions: dict[str, str] = field(default_factory=dict)
    memories: dict[str, list[str]] = field(default_factory=dict)
    calls: list[tuple[str, dict]] = field(default_factory=list)
    jobs: dict[str, dict] = field(default_factory=dict)

    # Behaviour switches for exercising the awkward paths.
    encode_document_changes: bool = True   # arrives JSON-encoded
    edits_document: bool = True            # False -> unbilled no-op chat
    fail_next: str | None = None
    fail_error: str = "upstream unavailable"
    fail_retryable: bool = True
    polls_before_terminal: int = 2         # in_progress before awaiting_approval
    ops_remaining: int = 9990

    _next_session: int = 0
    _next_change: int = 0
    _next_job: int = 0
    _poll_count: dict[str, int] = field(default_factory=dict)

    def call(self, tool: str, params: dict) -> dict:
        self.calls.append((tool, params))
        if self.fail_next == tool:
            self.fail_next = None
            return {"error": self.fail_error, "retryable": self.fail_retryable}
        handler = getattr(self, f"_{tool}", None)
        if handler is None:
            return {"error": f"unknown tool {tool}"}
        return handler(params)

    # --- sessions and documents -------------------------------------------

    def _init_session(self, params: dict) -> dict:
        if "document_ids" not in params:
            return {"error": "HTTP error 422: Unprocessable Entity - body "
                             "required"}
        self._next_session += 1
        session_id = f"session_init_{self._next_session:012x}"
        self.sessions[session_id] = f"<h1>Doc</h1><p>{OXFORD_BEFORE}</p>"
        return {"session_id": session_id, "opened": [],
                "focused_document_id": None, "documents": []}

    def _upload_document_base64(self, params: dict) -> dict:
        session_id = params.get("session_id")
        if session_id not in self.sessions:
            return {"error": f"unknown session {session_id}"}
        if "file_base64" not in params:
            return {"error": "HTTP error 422: file_base64 required"}
        html = base64.b64decode(params["file_base64"]).decode("utf-8")
        self.sessions[session_id] = html
        return {"html": html, "session_id": session_id,
                "filename": params.get("filename"), "chunks_count": 2,
                "version_id": "ver_fake", "page_setup": None,
                "persisted": True}

    def _export_document(self, params: dict) -> dict:
        session_id = params.get("session_id")
        if session_id not in self.sessions:
            return {"error": f"unknown session {session_id}"}
        return {"result": self.sessions[session_id]}

    def _request_download_url(self, params: dict) -> dict:
        session_id = params.get("session_id")
        if session_id not in self.sessions:
            return {"error": f"unknown session {session_id}"}
        return {"download_url": f"https://example.invalid/{session_id}",
                "expires_in_seconds": 900, "format": params.get("format")}

    # --- chat -------------------------------------------------------------

    def _record_memory(self, params: dict) -> None:
        if not params.get("cross_session_memory"):
            return
        key = params.get("cross_session_memory_key") or "default"
        self.memories.setdefault(key, []).append(params["message"])

    def _make_pending(self, session_id: str) -> dict:
        self._next_change += 1
        return {"change_id": f"chg_{self._next_change:06d}",
                "operation": "edit", "chunk_id": "chunk_fake",
                "document_id": "doc_primary",
                "old_html": f"<p>{OXFORD_BEFORE}</p>",
                "new_html": f"<p>{OXFORD_AFTER}</p>",
                "ai_explanation": "Added the serial comma."}

    def _chat(self, params: dict) -> dict:
        session_id = params.get("session_id")
        if session_id not in self.sessions:
            return {"error": f"unknown session {session_id}"}
        if "message" not in params:
            return {"error": "HTTP error 422: field 'message' required"}
        self._record_memory(params)

        ask = params.get("approval_mode") == "ask_every_time"
        billable = self.edits_document and not ask
        if billable:
            self.ops_remaining -= 1
            self.sessions[session_id] = f"<h1>Doc</h1><p>{OXFORD_AFTER}</p>"

        changes: dict[str, Any] = {
            "updated_html": self.sessions[session_id],
            "version_id": "ver_fake",
            "changes_summary": "1 section edited" if billable else None,
            "requires_approval": True if ask else None,
            "pending_changes": ([self._make_pending(session_id)]
                                if ask and self.edits_document else None),
            "changes": None, "chunk_diffs": None, "concurrent_merges": None,
        }
        payload: Any = (json.dumps(changes) if self.encode_document_changes
                        else changes)
        return {"response": "ok", "session_id": session_id,
                "document_changes": payload,
                "usage": {"was_billable": billable,
                          "ops_charged": 1 if billable else 0,
                          "monthly_used": 5, "monthly_limit": 500,
                          "bucket_used": "promo",
                          "promotions": [{"ops_remaining": self.ops_remaining}]},
                "hint": None}

    def _chat_async(self, params: dict) -> dict:
        session_id = params.get("session_id")
        if session_id not in self.sessions:
            return {"error": f"unknown session {session_id}"}
        self._record_memory(params)
        self._next_job += 1
        job_id = f"job_{self._next_job:06d}"
        self.jobs[job_id] = {
            "job_id": job_id, "session_id": session_id, "status": "pending",
            "metadata": {"pending_changes":
                         [self._make_pending(session_id)]
                         if self.edits_document else None},
            "_approved": set()}
        self._poll_count[job_id] = 0
        return {"job_id": job_id, "session_id": session_id,
                "status": "pending", "message": "Chat request queued"}

    def _get_job(self, params: dict) -> dict:
        job_id = params.get("job_id")
        job = self.jobs.get(job_id)
        if not job:
            return {"error": f"unknown job {job_id}"}
        self._poll_count[job_id] = self._poll_count.get(job_id, 0) + 1
        if job["status"] in ("pending", "in_progress"):
            job["status"] = ("in_progress"
                             if self._poll_count[job_id] <= self.polls_before_terminal
                             else "awaiting_approval")
        return {"job": {k: v for k, v in job.items() if not k.startswith("_")}}

    def _get_session_jobs(self, params: dict) -> dict:
        jobs = [{k: v for k, v in j.items() if not k.startswith("_")}
                for j in self.jobs.values()
                if j["session_id"] == params.get("session_id")]
        return {"jobs": jobs, "total": len(jobs)}

    def _approve_change(self, params: dict) -> dict:
        job = self.jobs.get(params.get("job_id"))
        if not job:
            return {"error": f"unknown job {params.get('job_id')}"}
        if job["status"] != "awaiting_approval":
            return {"error": "HTTP error 400: Job is not awaiting approval "
                             f"(status: {job['status']})"}
        change_id = params.get("change_id")
        if not change_id:
            # Observed live: succeeds, completes nothing, applies nothing.
            return {"status": "ok", "message": "Approval processed",
                    "batch_complete": False}
        job["_approved"].add(change_id)
        pending = job["metadata"].get("pending_changes") or []
        complete = len(job["_approved"]) >= len(pending)
        if complete:
            job["status"] = "completed"
            self.sessions[job["session_id"]] = f"<h1>Doc</h1><p>{OXFORD_AFTER}</p>"
            self.ops_remaining -= 1
        return {"status": "ok", "message": "Approval processed",
                "batch_complete": complete}

    # --- memory -----------------------------------------------------------

    def _clear_cross_session_memory(self, params: dict) -> dict:
        key = params.get("memory_key")
        removed = len(self.memories.pop(key, [])) if key else sum(
            len(v) for v in self.memories.values())
        if not key:
            self.memories.clear()
        return {"status": "ok", "memory_key": key, "removed": removed}
