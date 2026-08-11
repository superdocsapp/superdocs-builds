"""A stateful fake of the SuperDocs API, served over real HTTP.

Every response shape here was reconciled against a real recorded call - the cassettes in
`tests/fixtures/cassettes/` are the source of truth, not the documentation. Where the two
disagreed, the cassette won, and the disagreement is written up in BUGS.md.

What it models faithfully, because tests depend on it:

* the async job lifecycle, including the pause at `awaiting_approval`
* per-item approve/reject, where rejecting one change leaves the others alone
* chunk-addressed documents, so an approved edit lands in one block and no other block moves
* **one active job per session**, returning `409 session_busy` otherwise - the constraint that
  shapes the whole orchestrator (BUGS.md #8)
* `result.usage` with `ops_charged`, including turns billed for producing nothing (BUGS.md #2)
* export returning a raw file body rather than JSON (BUGS.md #7)
* attachment upload returning a job id, with the attachment id issued later (BUGS.md #5)

What it does not model: the actual AI. Proposals come from deterministic word substitution. A test
that depends on a model's wording is a test that fails on Tuesdays.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .blocks import Block, render_html, render_markdown, split_blocks

DEFAULT_API_KEY = "sk_fake_test_key"

#: Substitutions the fake "AI" proposes. Lowercase trigger -> replacement.
DEFAULT_STYLE_FIXES = {
    "utilise": "use",
    "utilize": "use",
    "leverage": "use",
    "in order to": "to",
}

ACTIVE = {"pending", "in_progress", "awaiting_approval"}
TERMINAL = {"completed", "failed", "cancelled"}


@dataclass
class Faults:
    """Failure injection. Tests set these to prove the client degrades rather than dies."""

    fail_next: int = 0
    fail_status: int = 503
    fail_paths: tuple[str, ...] = ()
    latency: float = 0.0
    attachment_polls_until_ready: int = 1
    job_polls_until_proposals: int = 1
    rogue_chunk: bool = False
    continue_prompt_first: bool = False
    #: The live API sends proposal HTML as a plain string. Kept as an option because the
    #: integration notes warn that some surfaces double-encode it, and the client tolerates both.
    double_encode: bool = False
    #: Reproduces the billed-but-produced-nothing turn from BUGS.md #2.
    refuse_to_act: bool = False
    retry_after: float | None = None

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


@dataclass
class JobState:
    job_id: str
    session_id: str
    message: str
    approval_mode: str
    polls: int = 0
    status: str = "pending"
    proposals: list[dict[str, Any]] = field(default_factory=list)
    decided: dict[str, bool] = field(default_factory=dict)
    continued: bool = False
    ops_charged: int = 1
    refused: bool = False
    error: str | None = None


@dataclass
class AttachmentState:
    job_id: str
    attachment_id: str
    session_id: str
    filename: str
    text: str
    polls: int = 0


class FakeSuperDocs:
    """Holds the state. `create_app` wraps it in HTTP; `serve()` runs it."""

    def __init__(self, api_key: str = DEFAULT_API_KEY):
        self.api_key = api_key
        self.faults = Faults()
        self.style_fixes = dict(DEFAULT_STYLE_FIXES)
        self.documents: dict[str, list[Block]] = {}
        self.attachments: dict[str, list[AttachmentState]] = {}
        self.jobs: dict[str, JobState] = {}
        self.operations_used = 0
        self.request_log: list[str] = []
        self._lock = threading.RLock()

    # -- helpers used by the routes -------------------------------------------------

    def blocks_for(self, session_id: str) -> list[Block]:
        return self.documents.get(session_id, [])

    def active_job_count(self, session_id: str) -> int:
        return sum(
            1 for j in self.jobs.values() if j.session_id == session_id and j.status in ACTIVE
        )

    def build_proposals(self, session_id: str) -> list[dict[str, Any]]:
        """Deterministic 'lint findings': one proposed change per style violation found."""
        proposals: list[dict[str, Any]] = []
        for block in self.blocks_for(session_id):
            if block.kind == "code":
                continue
            fixed = block.text
            hits: list[str] = []
            for trigger, replacement in self.style_fixes.items():
                if trigger in fixed.lower():
                    fixed = _replace_case_insensitive(fixed, trigger, replacement)
                    hits.append(trigger)
            if not hits:
                continue
            proposals.append(
                {
                    "change_id": str(uuid.uuid4()),
                    "operation": "edit",
                    "chunk_id": block.chunk_id,
                    "document_id": "doc_primary",
                    "old_html": self._encode(block.to_html()),
                    "new_html": self._encode(Block(block.chunk_id, fixed, block.kind).to_html()),
                    "ai_explanation": f"Style guide: prefer plainer wording ({', '.join(hits)}).",
                    "_replacement_markdown": fixed,
                }
            )
        if self.faults.rogue_chunk:
            # A change aimed at a chunk that is not in this document. Stands in for a proposal
            # produced by a document that tried to give the system orders.
            ghost = str(uuid.uuid4())
            proposals.append(
                {
                    "change_id": str(uuid.uuid4()),
                    "operation": "edit",
                    "chunk_id": ghost,
                    "document_id": "doc_primary",
                    "old_html": self._encode(f'<p data-chunk-id="{ghost}">nowhere</p>'),
                    "new_html": self._encode(f'<p data-chunk-id="{ghost}">injected</p>'),
                    "ai_explanation": "Injected proposal targeting a chunk outside the document.",
                    "_replacement_markdown": "injected",
                }
            )
        return proposals

    def _encode(self, html: str) -> Any:
        return json.dumps(html) if self.faults.double_encode else html

    def apply_decisions(self, job: JobState) -> None:
        """Write approved changes into the document. Rejected chunks are not touched at all."""
        blocks = self.documents.get(job.session_id)
        if blocks is None:
            return
        by_chunk = {b.chunk_id: b for b in blocks}
        for proposal in job.proposals:
            if not job.decided.get(proposal["change_id"], False):
                continue
            block = by_chunk.get(proposal.get("chunk_id") or "")
            if block is None:
                continue  # rogue chunk: nothing to write to, so nothing happens
            block.text = proposal["_replacement_markdown"]

    def public_proposals(self, job: JobState) -> list[dict[str, Any]]:
        return [{k: v for k, v in p.items() if not k.startswith("_")} for p in job.proposals]

    def usage_block(self, job: JobState) -> dict[str, Any]:
        """Mirrors the live `result.usage`, promo bucket and all."""
        return {
            "monthly_used": 0,
            "monthly_limit": 500,
            "monthly_remaining": 500,
            "was_billable": True,
            "ops_charged": job.ops_charged,
            "quota_exhausted": False,
            "subscription_tier": "free",
            "bucket_used": "promo",
            "promotions": [
                {
                    "name": "Round 2 Builders - August 2026",
                    "ops_granted": 10000,
                    "ops_remaining": 10000 - self.operations_used,
                    "expires_at": "2026-09-06T12:04:57",
                }
            ],
        }

    # -- server ---------------------------------------------------------------------

    @contextmanager
    def serve(self, host: str = "127.0.0.1"):
        """Run the fake on an ephemeral port; yields the base URL."""
        config = uvicorn.Config(
            create_app(self), host=host, port=0, log_level="error", access_log=False
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError("FakeSuperDocs did not start within 15s")
                time.sleep(0.02)
            port = server.servers[0].sockets[0].getsockname()[1]
            yield f"http://{host}:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def _replace_case_insensitive(text: str, needle: str, replacement: str) -> str:
    import re

    return re.sub(re.escape(needle), replacement, text, flags=re.IGNORECASE)


def create_app(fake: FakeSuperDocs) -> FastAPI:  # noqa: C901 - a router is a flat list of routes
    app = FastAPI(title="FakeSuperDocs")

    @app.middleware("http")
    async def gate(request: Request, call_next):
        """Auth, fault injection and request logging, before any route runs."""
        path = request.url.path
        fake.request_log.append(f"{request.method} {path}")

        if fake.faults.latency:
            time.sleep(fake.faults.latency)

        if not path.startswith("/_fake/"):
            if request.headers.get("authorization", "") != f"Bearer {fake.api_key}":
                return JSONResponse({"error": "invalid api key"}, status_code=401)

            with fake._lock:
                should_fail = fake.faults.fail_next > 0 or any(
                    fragment in path for fragment in fake.faults.fail_paths
                )
                if fake.faults.fail_next > 0:
                    fake.faults.fail_next -= 1
            if should_fail:
                headers = {}
                if fake.faults.retry_after is not None:
                    headers["Retry-After"] = str(fake.faults.retry_after)
                return JSONResponse(
                    {"error": "injected failure"},
                    status_code=fake.faults.fail_status,
                    headers=headers,
                )
        return await call_next(request)

    # -- test control plane ---------------------------------------------------------

    @app.post("/_fake/fault")
    async def set_fault(body: dict[str, Any]):
        for key, value in body.items():
            if not hasattr(fake.faults, key):
                raise HTTPException(400, f"unknown fault {key}")
            setattr(fake.faults, key, tuple(value) if key == "fail_paths" else value)
        return {"ok": True}

    @app.get("/_fake/state")
    async def get_state():
        return {
            "operations_used": fake.operations_used,
            "requests": len(fake.request_log),
            "request_log": fake.request_log,
            "jobs": {
                jid: {"status": j.status, "polls": j.polls, "decided": j.decided}
                for jid, j in fake.jobs.items()
            },
            "sessions": sorted(fake.documents),
        }

    @app.post("/_fake/reset")
    async def reset():
        with fake._lock:
            fake.faults.reset()
            fake.documents.clear()
            fake.attachments.clear()
            fake.jobs.clear()
            fake.operations_used = 0
            fake.request_log.clear()
        return {"ok": True}

    # -- attachments ----------------------------------------------------------------

    @app.post("/v1/attachments/upload-base64")
    async def upload_attachment(body: dict[str, Any]):
        session_id = body.get("session_id") or f"sess_{uuid.uuid4().hex[:8]}"
        text = base64.b64decode(body["file_base64"]).decode("utf-8", errors="replace")
        state = AttachmentState(
            job_id=str(uuid.uuid4()),
            attachment_id=str(uuid.uuid4()),
            session_id=session_id,
            filename=body.get("filename", "reference.md"),
            text=text,
        )
        with fake._lock:
            fake.attachments.setdefault(session_id, []).append(state)
        # Note: no attachment_id in this response. That is faithful to the live API (BUGS.md #5).
        return {
            "job_id": state.job_id,
            "filename": state.filename,
            "status": "processing",
            "message": f"Upload successful. Processing {state.filename}...",
        }

    @app.get("/v1/attachments/status/{session_id}")
    async def attachment_status(session_id: str):
        ready, processing = [], []
        with fake._lock:
            for state in fake.attachments.get(session_id, []):
                state.polls += 1
                is_ready = state.polls >= fake.faults.attachment_polls_until_ready
                processing.append(
                    {
                        "job_id": state.job_id,
                        "filename": state.filename,
                        "status": "completed" if is_ready else "processing",
                        "progress": 100 if is_ready else 40,
                        "error": None,
                        "attachment_id": state.attachment_id if is_ready else None,
                    }
                )
                if is_ready:
                    # Faithful detail: a ready attachment carries no `status` field.
                    ready.append(
                        {
                            "attachment_id": state.attachment_id,
                            "filename": state.filename,
                            "file_extension": ".md",
                            "chunks_count": len(split_blocks(state.text)),
                            "file_size": len(state.text),
                            "upload_timestamp": "2026-08-11T14:23:01.921089",
                        }
                    )
        return {
            "session_id": session_id,
            "ready_attachments": ready,
            "processing_jobs": processing,
            "total_ready": len(ready),
            "total_processing": len(processing) - len(ready),
        }

    # -- documents ------------------------------------------------------------------

    @app.post("/v1/documents/upload-base64")
    async def upload_document(body: dict[str, Any]):
        session_id = body.get("session_id") or f"sess_{uuid.uuid4().hex[:8]}"
        markdown = base64.b64decode(body["file_base64"]).decode("utf-8", errors="replace")
        blocks = split_blocks(markdown)
        with fake._lock:
            fake.documents[session_id] = blocks
        payload: dict[str, Any] = {
            "session_id": session_id,
            "filename": body.get("filename"),
            "chunks_count": len(blocks),
            "version_id": str(uuid.uuid4()),
            "page_setup": None,
            "persisted": True,
        }
        if body.get("return_html", False):
            payload["html"] = render_html(blocks)
        return payload

    @app.post("/v1/documents/export")
    async def export_document(body: dict[str, Any]):
        session_id = body.get("session_id", "")
        blocks = fake.blocks_for(session_id)
        content = render_markdown(blocks) if blocks else ""
        # Raw body, not JSON, matching the live service. Exports do not cost operations.
        return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")

    # -- chat, jobs and the gate ----------------------------------------------------

    @app.post("/v1/chat/async")
    async def start_async(body: dict[str, Any]):
        session_id = body["session_id"]
        with fake._lock:
            active = fake.active_job_count(session_id)
            if active:
                return JSONResponse(
                    {
                        "detail": {
                            "error_code": "session_busy",
                            "message": (
                                "The AI is still working on a previous request in this "
                                "conversation. Wait for it to finish or stop it, then send your "
                                "message again."
                            ),
                            "suggested_action": (
                                "Poll get_job/list_jobs for the active job, cancel it with "
                                "cancel_job, or use a different session_id."
                            ),
                            "active_jobs": active,
                        }
                    },
                    status_code=409,
                )
            job = JobState(
                job_id=str(uuid.uuid4()),
                session_id=session_id,
                message=body.get("message", ""),
                approval_mode=body.get("approval_mode", "ask_every_time"),
                refused=fake.faults.refuse_to_act,
            )
            fake.jobs[job.job_id] = job
            fake.operations_used += 1
        return {
            "job_id": job.job_id,
            "session_id": session_id,
            "status": "pending",
            "message": "Chat request queued for processing",
        }

    @app.get("/v1/jobs")
    async def list_jobs(session_id: str | None = None):
        with fake._lock:
            jobs = [
                j for j in fake.jobs.values() if session_id is None or j.session_id == session_id
            ]
            return [_job_payload(fake, j) for j in jobs]

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str):
        with fake._lock:
            job = fake.jobs.get(job_id)
            if job is None:
                raise HTTPException(404, "no such job")
            if job.status in TERMINAL:
                return _job_payload(fake, job)

            job.polls += 1
            if job.polls < fake.faults.job_polls_until_proposals:
                job.status = "in_progress"
                return _job_payload(fake, job)

            if job.refused:
                # Billed, but produced nothing and gave no findings. BUGS.md #2.
                job.status = "completed"
                return _job_payload(fake, job)

            if fake.faults.continue_prompt_first and not job.continued:
                job.status = "awaiting_approval"
                return _job_payload(fake, job, awaiting_kind="continue")

            if not job.proposals:
                job.proposals = fake.build_proposals(job.session_id)

            if not job.proposals:
                job.status = "completed"  # an honest report of no findings
                return _job_payload(fake, job)

            if job.approval_mode == "approve_all":
                job.decided = {p["change_id"]: True for p in job.proposals}
                fake.apply_decisions(job)
                job.status = "completed"
                return _job_payload(fake, job)

            job.status = "awaiting_approval"
            return _job_payload(fake, job, awaiting_kind="approval")

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        with fake._lock:
            job = fake.jobs.get(job_id)
            if job is None:
                raise HTTPException(404, "no such job")
            if job.status in TERMINAL:
                raise HTTPException(409, f"job already {job.status}")
            job.status = "cancelled"
            return {"job_id": job_id, "status": "cancelled"}

    @app.post("/v1/chat/{session_id}/approve")
    async def approve(session_id: str, body: dict[str, Any]):
        with fake._lock:
            job = fake.jobs.get(body.get("job_id", ""))
            if job is None or job.session_id != session_id:
                raise HTTPException(404, "no such job in this session")
            if "approved" not in body:
                raise HTTPException(422, "top-level 'approved' is required")

            default = bool(body["approved"])
            listed = body.get("changes")
            if isinstance(listed, list) and listed:
                for item in listed:
                    change_id = item.get("change_id")
                    if change_id is None:
                        raise HTTPException(422, "each change needs a change_id")
                    job.decided[change_id] = bool(item.get("approved", default))
            elif body.get("change_id"):
                job.decided[body["change_id"]] = default

            for proposal in job.proposals:
                job.decided.setdefault(proposal["change_id"], default)

            fake.apply_decisions(job)
            job.status = "completed"
            return {"status": "ok", "message": "Approval processed", "batch_complete": True}

    @app.post("/v1/chat/{session_id}/continue")
    async def continue_chat(session_id: str, body: dict[str, Any]):
        with fake._lock:
            job = fake.jobs.get(body.get("job_id", ""))
            if job is None or job.session_id != session_id:
                raise HTTPException(404, "no such job in this session")
            job.continued = True
            job.status = "in_progress" if body.get("continue", True) else "cancelled"
            return {"job_id": job.job_id, "status": job.status}

    # -- quota ----------------------------------------------------------------------

    @app.get("/v1/agents/whoami")
    async def whoami():
        # Faithfully omits the promo bucket, exactly as the live endpoint does (BUGS.md #1).
        return {
            "account_id": "00000000-0000-0000-0000-000000000000",
            "tier": "free",
            "quota": {
                "tier": "free",
                "monthly_limit": 500,
                "used": 0,
                "remaining": 500,
                "resets_at": "2026-09-01T00:00:00+00:00",
            },
            "is_agent_account": False,
            "adopted": None,
            "hint": None,
        }

    return app


def _job_payload(
    fake: FakeSuperDocs, job: JobState, *, awaiting_kind: str | None = None
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"message": job.message, "document_html_provided": True}
    if job.status == "awaiting_approval":
        metadata["awaiting_kind"] = awaiting_kind or "approval"
        if awaiting_kind != "continue":
            metadata["pending_changes"] = fake.public_proposals(job)
    else:
        metadata["pending_changes"] = None

    payload: dict[str, Any] = {
        "job_id": job.job_id,
        "session_id": job.session_id,
        "job_type": "chat",
        "status": job.status,
        "progress": 90 if job.status == "awaiting_approval" else 100,
        "error": job.error,
        "metadata": metadata,
        "result": None,
    }
    if job.status == "completed":
        payload["result"] = {
            "response": (
                "I wasn't able to determine an action for that request. Could you rephrase "
                "what you'd like me to change or answer?"
                if job.refused
                else "Lint pass complete."
            ),
            "session_id": job.session_id,
            "document_changes": None,
            "usage": fake.usage_block(job),
        }
    return payload
