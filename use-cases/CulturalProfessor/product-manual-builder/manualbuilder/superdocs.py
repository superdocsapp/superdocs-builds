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
        self._client = httpx.Client(
            base_url=self.base_url, timeout=timeout,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
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

    def upload(self, filename: str, content: str | bytes,
               content_type: str = "text/html") -> str:
        """Upload a document and return its id.

        The service parses an upload into HTML chunks, and chunk-level editing is
        what makes "this edit changed exactly this and nothing else" provable
        later. Uploading pre-chunked HTML rather than a flat blob is therefore
        not cosmetic.
        """
        data = content.encode("utf-8") if isinstance(content, str) else content
        body = self._post("/v1/documents/upload", {
            "filename": filename,
            "content_base64": base64.b64encode(data).decode("ascii"),
            "content_type": content_type,
        })
        document_id = body.get("document_id") or body.get("id")
        if not document_id:
            raise SuperDocsError(f"upload returned no document id: {body}")
        return str(document_id)

    def upload_image(self, filename: str, svg: str) -> str:
        """Upload an image and return a stable URL for an `<img src>`."""
        body = self._post("/v1/images/upload", {
            "filename": filename,
            "content_base64": base64.b64encode(svg.encode("utf-8")).decode("ascii"),
            "content_type": "image/svg+xml",
        })
        url = body.get("url") or body.get("image_url")
        if not url:
            raise SuperDocsError(f"image upload returned no url: {body}")
        return str(url)

    def export(self, document_id: str, fmt: str = "pdf") -> dict[str, Any]:
        """Exports are free, which is why the verification path leans on them."""
        return self._post("/v1/documents/export",
                          {"document_id": document_id, "format": fmt})

    # ----------------------------------------------------------------- chat --

    def chat(self, message: str, document_ids: list[str],
             session_id: str | None = None,
             open_mode: str = "background") -> dict[str, Any]:
        """One edit turn, parked for approval rather than applied.

        `document_ids` is a list because a turn can touch several open documents
        at once. That is the whole reason the manual and the card can't drift:
        one instruction produces both edits, so there is no window in which one
        document has been updated and the other has not.
        """
        payload: dict[str, Any] = {
            "message": message,
            "document_ids": document_ids,
            "approval_mode": "ask_every_time",
            "open_mode": open_mode,
        }
        if session_id:
            payload["session_id"] = session_id
        return self._post("/v1/chat", payload)

    def chat_async(self, message: str, document_ids: list[str],
                   session_id: str | None = None,
                   open_mode: str = "background") -> str:
        payload: dict[str, Any] = {
            "message": message,
            "document_ids": document_ids,
            "approval_mode": "ask_every_time",
            "open_mode": open_mode,
        }
        if session_id:
            payload["session_id"] = session_id
        body = self._post("/v1/chat/async", payload)
        job_id = body.get("job_id") or body.get("id")
        if not job_id:
            raise SuperDocsError(f"chat/async returned no job id: {body}")
        return str(job_id)

    def job(self, job_id: str) -> dict[str, Any]:
        return self._get(f"/v1/jobs/{job_id}")

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

    def approve(self, session_id: str, decisions: dict[str, bool],
                approved_by_default: bool = True) -> dict[str, Any]:
        """Approve or reject proposed changes, individually.

        `approved` is sent at the top level as well as per change. It is the
        default for any entry that omits its own, and omitting it approves
        nothing -- which looks exactly like a service that ignored the call.
        """
        return self._post(f"/v1/chat/{session_id}/approve", {
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
        metadata = payload.get("metadata") or {}
        raw = metadata.get("pending_changes")
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
    """Read a .env if one is present. Never overwrites what is already set."""
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


__all__ = ["SuperDocs", "SuperDocsError", "QuotaExceeded", "ProposedChange",
           "load_dotenv"]
