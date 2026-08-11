"""A thin client for the SuperDocs API.

Deliberately thin: it knows how to make a call and how to read a reply, and it
contains no decisions about the manual, the card, or when to edit what. Those
live in `session.py`. Keeping them apart is what lets the session logic be read
without also reading HTTP handling.

Three things here are not obvious from the endpoint list, and each one cost time
to find out:

**Approval is opt-in and has a trap.** `approval_mode="ask_every_time"` parks a
turn at `status: "awaiting_approval"` instead of applying it. When approving a
batch with mixed decisions, `approved` has to appear at the *top level* as well
as per-change -- it is the default for any entry that omits its own, and leaving
it out approves nothing.

**Proposed changes arrive parsed on one path and JSON-encoded on the other.**
`metadata.pending_changes` from polling is already a list. The double-encoded
string lives in `intermediate_responses[].content` where `type` is
`proposed_change_batch`, which is the streaming path. Integrators seeing
`undefined` in every diff field are reading SSE, not polling. `pending_changes()`
below handles both so no caller has to know which one it got.

**Deep operations take minutes with no visible progress.** That is still
processing. The poll loop waits rather than treating a long job as a failure.

## Which endpoints are verified, and which are not

Stated here because the difference matters to whoever runs this next.

*Verified against the live service:* the four-call spine --
`POST /v1/documents/upload`, `POST /v1/chat`, `POST /v1/chat/{id}/approve`,
`POST /v1/documents/export` -- and the two reply shapes for proposed changes.
Also `POST /v1/sessions/init`, `GET /v1/sessions/{id}/documents`,
`POST /v1/documents/images/upload-base64`, `POST /v1/chat/async` and the job
endpoints its poll loop reads. The image path in particular is not the one this
client first guessed: `/v1/images/upload` does not exist.

*Inferred, not yet exercised:* the template paths. The documented interface
names those capabilities as MCP tools (`upload_template_base64`,
`list_user_templates`) without naming their REST paths, so `/v1/templates/upload`
and `/v1/templates` are this client's guess at the convention the verified calls
follow. They are isolated in their own methods for that reason: if the
convention is different, two short methods change and nothing else does.

Nothing in the offline test suite depends on those paths being right, and
`check` and `build` never call them -- so a wrong guess here cannot make a
passing test lie about the parts of this project that are actually proven.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.superdocs.app"
POLL_INTERVAL = 3.0

#: A session runs one turn at a time. Anything in these states holds it, and a
#: second turn sent while one is outstanding comes back 409 `session_busy`.
ACTIVE_JOB_STATUSES = frozenset(
    {"pending", "queued", "in_progress", "running", "awaiting_approval"})
DEFAULT_TIMEOUT = 600.0


class SuperDocsError(RuntimeError):
    """The API refused, and the message says what it said."""


class QuotaExceeded(SuperDocsError):
    """429. Not a bug; the free tier is 500 operations a month."""


@dataclass(frozen=True)
class ProposedChange:
    """One edit the model wants to make to one chunk of one document."""
    change_id: str
    operation: str          # edit | create | delete
    chunk_id: str | None
    document_id: str | None
    old_html: str
    new_html: str
    explanation: str

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> ProposedChange:
        return cls(
            change_id=str(raw.get("change_id") or raw.get("id") or ""),
            operation=str(raw.get("operation") or "edit"),
            chunk_id=raw.get("chunk_id"),
            document_id=raw.get("document_id"),
            old_html=raw.get("old_html") or "",
            new_html=raw.get("new_html") or "",
            explanation=raw.get("ai_explanation") or raw.get("explanation") or "",
        )


class SuperDocs:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        key = api_key or os.environ.get("SUPERDOCS_API_KEY", "")
        if not key:
            raise SuperDocsError(
                "SUPERDOCS_API_KEY is not set. Copy .env.example to .env and put "
                "your key in it; the key is never read from anywhere else."
            )
        self.base_url = (base_url or os.environ.get("SUPERDOCS_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        # No client-wide Content-Type. httpx sets `application/json` for a
        # `json=` body and a multipart boundary for a `files=` body, and a
        # default here would override the boundary and make every upload a
        # malformed JSON request.
        self._client = httpx.Client(
            base_url=self.base_url, timeout=timeout,
            headers={"Authorization": f"Bearer {key}"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SuperDocs:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ plumbing --

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._read(self._client.post(path, json=payload))

    def _get(self, path: str) -> dict[str, Any]:
        return self._read(self._client.get(path))

    @staticmethod
    def _read(response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 429:
            raise QuotaExceeded(
                f"quota exceeded: {response.text[:300]}. Exports, downloads and "
                f"denied changes are free; edits and searches are not."
            )
        if response.status_code >= 400:
            raise SuperDocsError(
                f"{response.request.method} {response.request.url.path} "
                f"-> {response.status_code}: {response.text[:600]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise SuperDocsError(
                f"expected JSON from {response.request.url.path}, got "
                f"{response.text[:200]!r}"
            ) from exc

    # ------------------------------------------------------------ documents --

    def init_session(self, document_ids: list[str] | None = None) -> str:
        """Open a session. Everything else needs one.

        A session is the unit that holds documents, and `/v1/chat` requires one:
        there is no document-only call anywhere on the surface.
        """
        body = self._post("/v1/sessions/init",
                          {"document_ids": document_ids} if document_ids else {})
        session_id = body.get("session_id") or body.get("id")
        if not session_id:
            raise SuperDocsError(f"session init returned no id: {body}")
        return str(session_id)

    def upload(self, filename: str, content: str | bytes, session_id: str,
               open_mode: str = "background",
               content_type: str = "text/html") -> str:
        """Upload a document into a session and return its id.

        Multipart, not JSON, and that is the whole reason this method exists in
        this shape. The JSON sibling `/v1/documents/upload-base64` has no
        `open_mode` field, so it always replaces the focused document -- upload
        two documents through it and the first one is gone, with `200` and
        `"persisted": true` on both calls. `open_mode="background"` is what puts
        a second document *beside* the first instead of on top of it.

        The service parses the upload into HTML chunks and hands back
        `data-chunk-id` on every element, which is what makes a later edit
        provably confined to one chunk.
        """
        data = content.encode("utf-8") if isinstance(content, str) else content
        body = self._read(self._client.post(
            "/v1/documents/upload",
            files={"file": (filename, data, content_type)},
            data={"session_id": session_id, "open_mode": open_mode},
        ))
        document_id = body.get("document_id") or body.get("id")
        if not document_id:
            raise SuperDocsError(f"upload returned no document id: {list(body)}")
        if not body.get("persisted", True):
            raise SuperDocsError(
                f"{filename} was converted but not stored: "
                f"{body.get('how_to_persist', 'no session_id was accepted')}"
            )
        return str(document_id)

    def documents(self, session_id: str) -> list[dict[str, Any]]:
        """What the session currently holds, newest view.

        Worth reading after an upload rather than trusting the upload's own
        reply: these two disagreed with each other during development, and the
        session's list is the one the chat call goes on.
        """
        body = self._get(f"/v1/sessions/{session_id}/documents")
        listed = body.get("documents")
        return listed if isinstance(listed, list) else []

    def focus(self, session_id: str, document_id: str) -> dict[str, Any]:
        """Make a document the session's focused one.

        Export renders what the session is focused on, so getting both documents
        out means focusing each in turn. Be warned that this endpoint has
        returned a *different* document's title than the one it was asked to
        focus; `documents()` is the view to trust.
        """
        return self._post(
            f"/v1/sessions/{session_id}/documents/{document_id}/focus", {})

    def upload_image(self, filename: str, svg: str) -> str:
        """Upload an image and return a stable URL for an `<img src>`.

        `url` is the durable one. The reply also carries a `view_url` with a
        signature and an expiry on it, which renders today and 404s in a week --
        putting that one in a document is a manual whose diagrams disappear.
        """
        body = self._post("/v1/documents/images/upload-base64", {
            "image_base64": base64.b64encode(svg.encode("utf-8")).decode("ascii"),
            "filename": filename,
            "content_type": "image/svg+xml",
        })
        url = body.get("url")
        if not url:
            raise SuperDocsError(f"image upload returned no durable url: {list(body)}")
        return str(url)

    def export_bytes(self, session_id: str, fmt: str = "pdf",
                     filename: str | None = None) -> bytes:
        """The exported file itself.

        Keyed by session, not by document: export renders what the session is
        focused on. And it returns the *file*, not JSON describing one -- an
        `application/json` reply here means something went wrong, or that a
        future version started handing back a link, so both are handled and
        anything else is an error rather than an empty file written to disk with
        a reassuring message next to it.

        Exports are free, which is why the verification path leans on them.
        """
        payload: dict[str, Any] = {"session_id": session_id, "format": fmt}
        if filename:
            payload["filename"] = filename
        response = self._client.post("/v1/documents/export", json=payload)
        if response.status_code == 429:
            raise QuotaExceeded(f"quota exceeded on export: {response.text[:200]}")
        if response.status_code >= 400:
            raise SuperDocsError(
                f"POST /v1/documents/export -> {response.status_code}: "
                f"{response.text[:400]}")

        if not response.headers.get("content-type", "").startswith("application/json"):
            return response.content

        body = response.json()
        for key in ("content_base64", "file_base64", "data"):
            if body.get(key):
                return base64.b64decode(body[key])
        for key in ("url", "download_url", "file_url"):
            if body.get(key):
                linked = self._client.get(body[key])
                if linked.status_code >= 400:
                    raise SuperDocsError(
                        f"export URL {body[key]} -> {linked.status_code}")
                return linked.content
        raise SuperDocsError(
            f"export of session {session_id} returned JSON carrying neither file "
            f"content nor a URL: {list(body)}"
        )

    # ----------------------------------------------------------------- chat --

    def chat(self, message: str, session_id: str,
             document_id: str | None = None) -> dict[str, Any]:
        """One edit turn, parked for approval rather than applied.

        One turn, one document. A session can hold several documents like tabs,
        and a turn can *read* across them, but the changes it proposes land in
        one -- the one named by `document_id`, falling back to whichever is
        focused. There is no call that edits two documents at once.

        That is worth being blunt about, because an earlier version of this
        client sent `document_ids` as a list and looked like it worked: the
        service accepts unknown fields, the reply comes back with proposed
        changes, and every one of them is in the focused document. Keeping the
        manual and the card consistent is therefore not something a single
        request can buy -- see `session.edit_both`, which buys it at the
        approval gate instead.
        """
        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": "ask_every_time",
        }
        if document_id:
            payload["document_id"] = document_id
        return self._post("/v1/chat", payload)

    def chat_async(self, message: str, session_id: str,
                   document_id: str | None = None) -> str:
        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": "ask_every_time",
        }
        if document_id:
            payload["document_id"] = document_id
        body = self._post("/v1/chat/async", payload)
        job_id = body.get("job_id") or body.get("id")
        if not job_id:
            raise SuperDocsError(f"chat/async returned no job id: {body}")
        return str(job_id)

    def job(self, job_id: str) -> dict[str, Any]:
        return self._get(f"/v1/jobs/{job_id}")

    def jobs(self, session_id: str) -> list[dict[str, Any]]:
        body = self._get(f"/v1/sessions/{session_id}/jobs")
        listed = body.get("jobs")
        return listed if isinstance(listed, list) else []

    def active_jobs(self, session_id: str) -> list[dict[str, Any]]:
        """Jobs holding the session: still running, or waiting to be approved.

        A session takes one turn at a time. Sending another while one is
        outstanding returns 409 `session_busy`, and the outstanding one is
        usually a batch somebody proposed and walked away from -- so the useful
        thing is to name it rather than to retry.
        """
        return [job for job in self.jobs(session_id)
                if str(job.get("status")) in ACTIVE_JOB_STATUSES]

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Throw a turn away, including one parked at `awaiting_approval`."""
        return self._post(f"/v1/jobs/{job_id}/cancel", {})

    def wait_for_job(self, job_id: str, timeout: float = DEFAULT_TIMEOUT,
                     poll: float = POLL_INTERVAL) -> dict[str, Any]:
        """Poll until the job stops moving.

        Deep operations run thirty seconds to several minutes with no visible
        progress, so a short timeout here reports a working service as broken.
        """
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.job(job_id)
            status = str(last.get("status", ""))
            if status in ("awaiting_approval", "completed", "failed", "error"):
                return last
            time.sleep(poll)
        raise SuperDocsError(
            f"job {job_id} still {last.get('status')!r} after {timeout:.0f}s")

    def approve(self, session_id: str, job_id: str, decisions: dict[str, bool],
                approved_by_default: bool = True) -> dict[str, Any]:
        """Approve or reject proposed changes, individually.

        `job_id` and `approved` are both required, and `approved` is the default
        for any entry in `changes` that omits its own -- so leaving it out
        approves nothing while looking exactly like a service that ignored the
        call. It is sent at the top level *and* per change for that reason.
        """
        return self._post(f"/v1/chat/{session_id}/approve", {
            "job_id": job_id,
            "approved": approved_by_default,
            "changes": [{"change_id": change_id, "approved": ok}
                        for change_id, ok in decisions.items()],
        })

    # -------------------------------------------------------------- reading --

    @staticmethod
    def pending_changes(payload: dict[str, Any]) -> list[ProposedChange]:
        """Every proposed change in a reply, whichever path it arrived on.

        Polling puts a parsed list in `metadata.pending_changes`. Streaming puts
        a JSON-encoded *string* in `intermediate_responses[].content` for the
        entry whose type is `proposed_change_batch`. Both are handled here so no
        caller has to know which one it is holding, and so the double-parse is
        written once instead of being rediscovered.
        """
        # The synchronous reply nests them under `document_changes`; the job
        # object puts the same already-parsed list under `metadata`. Both are
        # lists, and both are checked because a caller holding one of them
        # should not have to know which call produced it.
        for container in (payload.get("document_changes"), payload.get("metadata")):
            raw = (container or {}).get("pending_changes")
            if isinstance(raw, list):
                return [ProposedChange.from_payload(item) for item in raw]

        out: list[ProposedChange] = []
        for entry in payload.get("intermediate_responses") or []:
            if entry.get("type") != "proposed_change_batch":
                continue
            content = entry.get("content")
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except ValueError as exc:
                    raise SuperDocsError(
                        f"proposed_change_batch content was not JSON: "
                        f"{content[:200]!r}"
                    ) from exc
            for item in _batch_items(content):
                out.append(ProposedChange.from_payload(item))
        return out

    # ------------------------------------------------------------ templates --

    def upload_template(self, name: str, html: str) -> str:
        body = self._post("/v1/templates/upload", {
            "name": name,
            "content_base64": base64.b64encode(html.encode("utf-8")).decode("ascii"),
        })
        template_id = body.get("template_id") or body.get("id")
        if not template_id:
            raise SuperDocsError(f"template upload returned no id: {body}")
        return str(template_id)

    def templates(self) -> list[dict[str, Any]]:
        body = self._get("/v1/templates")
        listed = body.get("templates")
        return listed if isinstance(listed, list) else []


def _batch_items(content: Any) -> list[dict[str, Any]]:
    """A batch is either a list of changes or an object grouping them."""
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    if isinstance(content, dict):
        for key in ("changes", "pending_changes", "proposed_changes"):
            value = content.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        # Grouped by document id: {"doc_1": [...], "doc_2": [...]}
        out: list[dict[str, Any]] = []
        for value in content.values():
            if isinstance(value, list):
                out.extend(item for item in value if isinstance(item, dict))
        return out
    return []


def load_dotenv(path: str | Path = ".env") -> None:
    """Read a .env if one is present. Never overwrites what is already set.

    Quotes are stripped, and that is not tidiness. `KEY="sk_live_..."` is how
    half the world writes a .env, and keeping the quotes sends a bearer token
    with two extra characters in it -- which comes back as 401 *invalid
    credentials*, so the hour goes on the key being wrong rather than on the
    parsing being wrong. An `export ` prefix, from a file someone was sourcing
    in a shell, goes the same way.
    """
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


__all__ = ["SuperDocs", "SuperDocsError", "QuotaExceeded", "ProposedChange",
           "load_dotenv"]
