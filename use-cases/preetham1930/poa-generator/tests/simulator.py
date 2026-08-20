"""A SuperDocs stand-in whose behaviours are the ones we measured.

This is not a mock that returns what it was told to return. It holds a real
document, parses it with our own chunk parser, and reproduces five behaviours
recorded on 2026-08-09 and over Phase 4's live runs:

- an upload is verbatim, and comes back with a `data-chunk-id` per top-level
  element (measured: five chunks for a styled HTML upload, table atomic);
- `chat/async` with `approval_mode: ask_every_time` holds the change at
  `awaiting_approval` and applies **nothing** until the batch settles;
- an approved change lands only when the batch completes;
- `not_applied` (the mid-document insertion that vanished), `applied_wrong` and
  `collateral` (the create that appended sections nobody asked for) are the
  three recorded failure shapes, and each is optional;
- `paraphrase_notice` is new to this build and is the one that matters here: an
  edit lands correctly **and** the product quietly rewords a notice chunk it was
  never asked about. Every step passes. The document is still not exportable.
  It is a specialisation of the collateral-damage class that also fires on the
  notice gate, which is why it is worth simulating separately.

The assertions in the tests are about **our** behaviour - does the queue halt,
is the ledger row written before the actuator, is an export produced - not about
the simulator's.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from poa.chunks import ChunkMap

CHUNK_TAG = re.compile(r"<([a-zA-Z0-9]+)(\s|>)")


@dataclass
class Behaviour:
    """What the simulator does on a given **chat call** (1-based, not step).

    A retry is a second chat call for the same step, so `not_applied={2, 3}`
    means "step 2 fails and so does its one narrow retry", while
    `not_applied={2}` means "step 2 fails and the retry lands".
    """

    not_applied: set[int] = field(default_factory=set)
    applied_wrong: set[int] = field(default_factory=set)
    collateral: set[int] = field(default_factory=set)
    paraphrase_notice: set[int] = field(default_factory=set)
    drop_notice: set[int] = field(default_factory=set)
    corrupt_notice_on_upload: str = ""  # "paraphrase" | "drop" | ""
    fail_upload_verbatim: bool = False
    revert_works: bool = True


class SimulatedSuperDocs:
    def __init__(self, behaviour: Behaviour | None = None) -> None:
        self.behaviour = behaviour or Behaviour()
        self.html = ""
        self.pristine = ""
        self.document_id = "doc-" + uuid.uuid4().hex[:8]
        self.session_id = "session_init_" + uuid.uuid4().hex[:12]
        self.jobs: dict[str, dict[str, Any]] = {}
        self.step_index = 0
        self.exports: list[str] = []
        self.reverts = 0
        self.approve_calls: list[str] = []
        self.event_log: list[str] = []

    # -- transport ---------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = json_body or {}
        if method == "POST" and path == "/v1/sessions/init":
            return {"session_id": self.session_id, "opened": [], "focused_document_id": None}
        if method == "POST" and path == "/v1/documents/upload-base64":
            import base64

            raw = base64.b64decode(body["file_base64"]).decode("utf-8")
            if self.behaviour.fail_upload_verbatim:
                raw = raw.replace("</p>", " (edited on ingest)</p>", 1)
            self.html = _assign_chunk_ids(raw)
            if self.behaviour.corrupt_notice_on_upload:
                self._touch_notice(self.behaviour.corrupt_notice_on_upload)
            self.pristine = self.html
            return {
                "session_id": self.session_id,
                "filename": body["filename"],
                "chunks_count": len(ChunkMap(self.html)),
                "persisted": True,
            }
        if method == "GET" and path == f"/v1/sessions/{self.session_id}/documents":
            return {
                "session_id": self.session_id,
                "focused_document_id": "doc_primary",
                "documents": [
                    {
                        "document_id": "doc_primary",
                        "durable_document_id": self.document_id,
                        "chunks_count": len(ChunkMap(self.html)),
                        "focused": True,
                    }
                ],
            }
        if method == "GET" and path == f"/v1/documents/{self.document_id}":
            return {"document_id": self.document_id, "html": self.html, "version": 1}
        if method == "POST" and path == "/v1/chat/async":
            return {"job_id": self._plan_job(body["message"])}
        if method == "GET" and path.startswith("/v1/jobs/"):
            return self.jobs[path.rsplit("/", 1)[1]]
        if path.endswith("/approve"):
            self.approve_calls.append(body["change_id"])
            self.event_log.append(f"approve:{body['change_id']}")
            self._settle(body["job_id"], body["approved"])
            return {"status": "ok", "batch_complete": True}
        if path == "/v1/documents/export":
            self.exports.append(body.get("format", "docx"))
            return {"download_url": "https://example.invalid/x"}
        if path.endswith("/revert"):
            self.reverts += 1
            if self.behaviour.revert_works:
                self.html = self.pristine
            else:
                # The call returns ok and the document is not restored. This is
                # the shape the whole build is built against: a 200 means the
                # call was accepted, not that the state is what it claims.
                self.html += '\n<p data-chunk-id="rv-1">not actually reverted</p>'
            return {"status": "ok"}
        raise AssertionError(f"the simulator was asked for {method} {path}")

    def download(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> tuple[str, bytes]:
        self.request(method, path, json_body=json_body)
        return (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PKsimulated-docx",
        )

    # -- behaviour ---------------------------------------------------------

    def _plan_job(self, message: str) -> str:
        self.step_index += 1
        chunk_id = re.search(r"data-chunk-id is ([0-9a-zA-Z-]+)", message).group(1)
        new_html = message.split("\n\n", 1)[1]
        job_id = "job-" + uuid.uuid4().hex[:8]
        self.jobs[job_id] = {
            "job_id": job_id,
            "status": "awaiting_approval",
            "progress": 88,
            "metadata": {
                "pending_changes": [
                    {
                        "change_id": "chg-" + uuid.uuid4().hex[:8],
                        "chunk_id": chunk_id,
                        "operation": "edit",
                        "old_html": ChunkMap(self.html).by_id[chunk_id].html,
                        "new_html": new_html,
                    }
                ]
            },
            "_chunk_id": chunk_id,
            "_new_html": new_html,
            "_step": self.step_index,
        }
        return job_id

    def _settle(self, job_id: str, approved: bool) -> None:
        job = self.jobs[job_id]
        job["status"] = "completed"
        job["progress"] = 100
        job["metadata"]["pending_changes"] = []
        if not approved:
            return
        step = job["_step"]
        chunk_id, new_html = job["_chunk_id"], job["_new_html"]
        if step in self.behaviour.not_applied:
            self.event_log.append(f"step{step}:silently-did-nothing")
            return
        if step in self.behaviour.applied_wrong:
            new_html = new_html.replace("</p>", " (paraphrased)</p>")
        self._replace(chunk_id, new_html)
        if step in self.behaviour.collateral:
            self.event_log.append(f"step{step}:appended-clauses-nobody-asked-for")
            self.html += (
                '\n<h2 data-chunk-id="fab-1">99. Compensation of the agent</h2>'
                '\n<p data-chunk-id="fab-2">The Agent may take reasonable compensation.</p>'
            )
        if step in self.behaviour.paraphrase_notice:
            self.event_log.append(f"step{step}:reworded-a-notice-nobody-asked-about")
            self._touch_notice("paraphrase")
        if step in self.behaviour.drop_notice:
            self.event_log.append(f"step{step}:deleted-a-notice-nobody-asked-about")
            self._touch_notice("drop")

    def _touch_notice(self, how: str) -> None:
        """Reword or delete a notice chunk, without being asked to.

        The paraphrase is deliberately harmless-looking: 'is not legal advice'
        becomes 'is not intended as legal advice', which reads better and means
        something weaker. That is the shape a rewrite actually takes.
        """
        chunks = ChunkMap(self.html)
        target = next(
            (c for c in chunks.chunks if "not legal advice" in c.html),
            None,
        )
        if target is None:
            return
        if how == "drop":
            self.html = self.html.replace(target.html, "", 1)
            return
        self.html = self.html.replace(
            target.html,
            target.html.replace("It is not legal advice", "It is not intended as legal advice"),
            1,
        )

    def _replace(self, chunk_id: str, new_html: str) -> None:
        current = ChunkMap(self.html)
        old = current.by_id[chunk_id].html
        replacement = _with_chunk_id(new_html, chunk_id)
        self.html = self.html.replace(old, replacement, 1)


def _assign_chunk_ids(html: str) -> str:
    out: list[str] = []
    for line in html.split("\n"):
        match = CHUNK_TAG.match(line)
        if match:
            out.append(_with_chunk_id(line, "c-" + uuid.uuid4().hex[:12]))
        else:
            out.append(line)
    return "\n".join(out)


def _with_chunk_id(fragment: str, chunk_id: str) -> str:
    fragment = re.sub(r'\sdata-chunk-id="[^"]*"', "", fragment, count=1)
    return re.sub(r"<([a-zA-Z0-9]+)", rf'<\1 data-chunk-id="{chunk_id}"', fragment, count=1)
