"""The SuperDocs client, with the wire rules enforced in the client itself.

Four measured decisions live here rather than in a caller's discipline:

- **Decision 32** - gated changes go to `/v1/chat/async`. The gate takes a
  `job_id` and jobs exist only on the async route; passing `approval_mode` to
  the synchronous route leaves nothing to approve against. `chat_gated` is the
  only method that can produce a pending change and it cannot reach `/v1/chat`.
- **Decision 35** - one change per job, on the sending side. The answering side
  does not always agree: the first live run of this build asked for one chunk by
  id and got a two-change batch back. So we approve exactly the change we
  computed and deny every other one bare, and the read-back is what makes that
  safe rather than the batch size.
- **Decision 34** - a denial carries no feedback. `deny()` takes no feedback
  parameter, so there is no call shape in which one can be sent. Feedback
  triggers a revision pass, and the revision pass proposed edits to two chunks
  nobody targeted, aimed at the section headings.
- **Decision 33** - `approve` is an actuator, not a record. This client returns
  what the API returned and claims nothing about what was decided; the decision
  ledger is written by the caller, before the call.

Nothing here believes a reply. `read_back()` is the only method whose result is
evidence, and it is the only one the verifier consults.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..chunks import ChunkMap
from ..errors import PlanRefusedError
from .transport import Transport

TERMINAL = {"completed", "failed", "cancelled", "error"}


@dataclass
class PendingChange:
    change_id: str
    chunk_id: str
    operation: str
    old_html: str
    new_html: str


@dataclass
class Job:
    job_id: str
    status: str
    progress: int
    pending: list[PendingChange]
    raw: dict[str, Any]

    @property
    def awaiting(self) -> bool:
        return self.status == "awaiting_approval"

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL


class SuperDocsClient:
    def __init__(self, transport: Transport, *, poll_seconds: float = 3.0, max_polls: int = 80):
        self.transport = transport
        self.poll_seconds = poll_seconds
        self.max_polls = max_polls
        self.billable_calls = 0
        self.export_content_types: list[str] = []

    # -- documents ---------------------------------------------------------

    def upload_verbatim(self, filename: str, html: str) -> tuple[str, str]:
        """Upload our computed skeleton. Returns (document_id, session_id).

        Verbatim is the load-bearing property (Decision 29) and it is checked by
        the caller against a read-back, never assumed from this response.
        """
        # Three calls, and the third is the one that makes the other two
        # checkable. An upload with no session is not persisted, and the upload
        # response carries no document id at all - so the id comes from the
        # session's own roster, which is a read rather than a claim.
        session = self.transport.request("POST", "/v1/sessions/init", json_body={})
        session_id = session.get("session_id")
        if not session_id:
            raise RuntimeError(f"sessions/init returned no session_id; keys {sorted(session)}")
        payload = {
            "filename": filename,
            "file_base64": base64.b64encode(html.encode("utf-8")).decode("ascii"),
            "session_id": session_id,
        }
        # One retry, because a 503 with an empty body was observed on a 23 KB
        # upload and succeeded immediately on the next attempt. A retried POST
        # could leave two documents in the session, so the roster below is
        # required to hold exactly one - the retry is checked, not trusted.
        try:
            uploaded = self.transport.request(
                "POST", "/v1/documents/upload-base64", json_body=payload
            )
        except RuntimeError as exc:
            if "HTTP 5" not in str(exc):
                raise
            uploaded = self.transport.request(
                "POST", "/v1/documents/upload-base64", json_body=payload
            )
        if not uploaded.get("persisted"):
            raise RuntimeError(
                f"the upload reports persisted={uploaded.get('persisted')!r}. An unpersisted "
                f"document cannot be read back, and a read-back is the only evidence there is."
            )
        roster = self.transport.request("GET", f"/v1/sessions/{session_id}/documents")
        documents = roster.get("documents") or []
        if len(documents) > 1:
            raise RuntimeError(
                f"the session holds {len(documents)} documents and this build works on one. "
                f"If an upload was retried after a 5xx, both may have landed; nothing is edited "
                f"until a human has looked."
            )
        durable = next(
            (d.get("durable_document_id") for d in documents if d.get("durable_document_id")), None
        )
        if not durable:
            raise RuntimeError(
                f"the session roster carries no durable document id; {len(documents)} "
                f"document(s), keys {sorted(documents[0]) if documents else '(none)'}. "
                f"Without one there is nothing to verify against."
            )
        return durable, session_id

    def read_back(
        self, document_id: str, *, attempts: int = 4, sleep=time.sleep
    ) -> tuple[ChunkMap, dict[str, Any]]:
        """`GET /v1/documents/{id}?include_html=true` - the only evidence there is.

        Retried on a 404 because the durable record is not always queryable the
        instant the upload returns: one run 404'd immediately and the same call
        returned 200 on the next attempt. A read is safe to repeat; the retry is
        bounded and a persistent 404 stops the run rather than being smoothed
        over into "nothing to verify".
        """
        body: dict[str, Any] = {}
        for attempt in range(attempts):
            try:
                body = self.transport.request(
                    "GET", f"/v1/documents/{document_id}", params={"include_html": "true"}
                )
                break
            except RuntimeError as exc:
                if "HTTP 404" not in str(exc) or attempt == attempts - 1:
                    raise
                sleep(2.0 * (attempt + 1))
        html = body.get("html")
        if not html:
            raise RuntimeError(
                f"read-back for {document_id} carried no html. A verification step that "
                f"cannot see the document verifies nothing."
            )
        return ChunkMap(html), body

    def export(self, session_id: str, fmt: str, out_dir: Path | None = None) -> Path | None:
        """The export answers with a file, not with JSON, so it gets its own path.

        Written to disk when `out_dir` is given, because an export nobody can
        open is not evidence of anything.
        """
        content_type, blob = self.transport.download(
            "POST", "/v1/documents/export", json_body={"session_id": session_id, "format": fmt}
        )
        self.export_content_types.append(content_type)
        if out_dir is None or not blob:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"statements.{fmt}"
        path.write_bytes(blob)
        return path

    def revert(self, session_id: str, turn_index: int) -> dict[str, Any]:
        return self.transport.request(
            "POST", f"/v1/sessions/{session_id}/revert", json_body={"turn_index": turn_index}
        )

    # -- the gated edit loop ----------------------------------------------

    def chat_gated(self, session_id: str, document_id: str, instruction: str) -> Job:
        """One instruction, on the async route, held at the gate (Decisions 32 and 35).

        `document_id` is not sent: the session holds exactly one document and it
        is focused, and the durable id we verify against is not the id the chat
        surface uses for it. Naming the wrong one is worse than naming none.
        """
        del document_id
        body = self.transport.request(
            "POST",
            "/v1/chat/async",
            json_body={
                "session_id": session_id,
                "message": instruction,
                "approval_mode": "ask_every_time",
                "response_mode": "compact",
            },
        )
        self.billable_calls += 1
        job_id = body.get("job_id")
        if not job_id:
            raise RuntimeError(f"chat/async returned no job_id; keys {sorted(body)}")
        return self.poll(job_id)

    def poll(self, job_id: str, *, until_terminal: bool = False, sleep=time.sleep) -> Job:
        for _ in range(self.max_polls):
            body = self.transport.request("GET", f"/v1/jobs/{job_id}")
            job = _job_from(body)
            if job.finished or (job.awaiting and not until_terminal):
                return job
            sleep(self.poll_seconds)
        raise TimeoutError(
            f"job {job_id} did not settle in {self.max_polls} polls. Nothing is reported as "
            f"applied on a timeout; the document is read back and the run halts."
        )

    def approve(self, session_id: str, job_id: str, change_id: str) -> dict[str, Any]:
        return self.transport.request(
            "POST",
            f"/v1/chat/{session_id}/approve",
            json_body={"job_id": job_id, "change_id": change_id, "approved": True},
        )

    def deny(self, session_id: str, job_id: str, change_id: str) -> dict[str, Any]:
        """Bare. There is no feedback parameter, because feedback re-plans (Decision 34)."""
        return self.transport.request(
            "POST",
            f"/v1/chat/{session_id}/approve",
            json_body={"job_id": job_id, "change_id": change_id, "approved": False},
        )


def select_our_change(
    job: Job, expected_chunk_id: str
) -> tuple[PendingChange, list[PendingChange]]:
    """Split a batch into the one change we asked for and everything else.

    We send one chunk per job (Decision 35) and the product does not always
    answer with one. Measured on the first live run of this build: an
    instruction naming a single chunk id came back as a **two**-change batch,
    the second on a chunk nobody targeted - the same shape as the unprompted
    heading edits recorded on 2026-08-09.

    So the rule is not "the batch must be one"; it is **we approve exactly the
    change we computed and deny every other one, bare** (Decision 34). The
    read-back afterwards is what makes that safe: if a denial did not hold, the
    non-target chunk moved and the verifier calls it collateral damage.
    """
    ours = next((c for c in job.pending if c.chunk_id == expected_chunk_id), None)
    if ours is None:
        raise PlanRefusedError(
            f"job {job.job_id} proposes {len(job.pending)} change(s), none of them on chunk "
            f"{expected_chunk_id}, which is the one the step targets. Chunks proposed: "
            f"{[c.chunk_id for c in job.pending]}. Every one is denied; nothing is approved on "
            f"the strength of a proposal we did not ask for."
        )
    if ours.operation != "edit":
        raise PlanRefusedError(
            f"job {job.job_id} proposes operation {ours.operation!r} on our target. There is "
            f"one verb and it is replace (Decision 28)."
        )
    return ours, [c for c in job.pending if c is not ours]


def _job_from(body: dict[str, Any]) -> Job:
    metadata = body.get("metadata") or {}
    pending = [
        PendingChange(
            change_id=c.get("change_id", ""),
            chunk_id=c.get("chunk_id", ""),
            operation=c.get("operation", ""),
            old_html=c.get("old_html", "") or "",
            new_html=c.get("new_html", "") or "",
        )
        for c in (metadata.get("pending_changes") or [])
    ]
    return Job(
        job_id=body.get("job_id", ""),
        status=body.get("status", ""),
        progress=int(body.get("progress") or 0),
        pending=pending,
        raw=body,
    )
