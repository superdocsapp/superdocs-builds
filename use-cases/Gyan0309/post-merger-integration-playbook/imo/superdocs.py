"""A SuperDocs API client covering the four-call contract.

Upload, chat, approve, export. The brief is explicit that these four come first and
everything else is optional depth, so this client does those four properly rather than
covering the whole API shallowly.

Almost every non-obvious line here exists because of something that bit during
integration, and each is commented where it bites. The full list, with reproductions,
is in BUGS.md.

The verified flow, end to end:

    1. POST /v1/documents/upload-base64   with session_id  → persists the document
    2. GET  /v1/sessions/{id}/documents                    → document_id ("doc_primary")
    3. POST /v1/chat/async                                 → job_id
    4. GET  /v1/jobs/{job_id}                              → poll; changes arrive in
                                                             metadata.pending_changes
    5. POST /v1/chat/{session_id}/approve                  → job_id + change_id + approved
    6. POST /v1/documents/export                           → session_id + format
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("imo.superdocs")

DEFAULT_BASE_URL = "https://api.superdocs.app/v1"

REQUEST_TIMEOUT_SECONDS = 120.0
POLL_INTERVAL_SECONDS = 3.0
POLL_CEILING_SECONDS = 900.0

# Statuses that mean the job has stopped moving. Deliberately expressed as the set of
# *terminal* states rather than the set of working ones: the working vocabulary
# includes `in_progress`, and a poller that lists only pending/processing/running/queued
# treats `in_progress` as finished, reads a null result, and reports no changes at all.
TERMINAL_STATUSES = {
    "completed",
    "complete",
    "succeeded",
    "success",
    "failed",
    "error",
    "cancelled",
    "canceled",
    "awaiting_approval",
}

EXPORT_FORMATS = {"docx", "pdf", "html", "markdown", "txt"}


class SuperDocsError(RuntimeError):
    """An API call failed in a way the caller cannot recover from."""


@dataclass
class UploadedDocument:
    session_id: str
    document_id: str
    durable_document_id: str | None
    filename: str
    chunks_count: int = 0
    version_id: str | None = None


@dataclass
class PendingChange:
    change_id: str
    operation: str
    chunk_id: str | None
    document_id: str | None
    old_html: str
    new_html: str
    explanation: str

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> PendingChange:
        return cls(
            change_id=raw["change_id"],
            operation=raw.get("operation", "edit"),
            chunk_id=raw.get("chunk_id"),
            document_id=raw.get("document_id"),
            old_html=raw.get("old_html") or "",
            new_html=raw.get("new_html") or "",
            explanation=raw.get("ai_explanation") or "",
        )


@dataclass
class ChatResult:
    session_id: str
    job_id: str
    status: str
    pending_changes: list[PendingChange] = field(default_factory=list)
    response_text: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def awaiting_approval(self) -> bool:
        return self.status == "awaiting_approval"


def parse_embedded_json(raw: Any) -> Any:
    """Second-parse a field that arrives as a JSON-encoded string.

    The brief warns that proposed-change content arrives JSON-encoded and needs a
    second parse, and that missing this is the commonest cause of diff cards full of
    `undefined`. Worth being precise about *where* it applies, because it is not where
    you would first look:

      metadata.pending_changes[]              → already objects, no second parse
      metadata.intermediate_responses[]       → `content` IS a JSON string for entries
                                                of type `proposed_change_batch`

    So a client reading pending_changes is fine, and one reading the streamed
    intermediate responses must parse twice.
    """
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


class SuperDocsClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._key = api_key or os.environ.get("SUPERDOCS_API_KEY", "")
        if not self._key:
            raise SuperDocsError(
                "SUPERDOCS_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self._base = (
            base_url or os.environ.get("SUPERDOCS_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout = timeout
        self.calls_made = 0

    # -- plumbing ------------------------------------------------------------

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "<redacted>") if self._key else text

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        started = time.monotonic()

        try:
            with httpx.Client(timeout=timeout or self._timeout) as client:
                response = client.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                    },
                    json=json_body,
                )
        except httpx.RequestError as exc:
            raise SuperDocsError(
                f"{method} {path} unreachable: {type(exc).__name__}"
            ) from exc

        self.calls_made += 1
        logger.info(
            "%s %s -> %s in %.1fs",
            method,
            path,
            response.status_code,
            time.monotonic() - started,
        )

        if response.status_code >= 400:
            raise SuperDocsError(
                f"{method} {path} -> HTTP {response.status_code}: "
                f"{self._redact(response.text[:600])}"
            )

        return response.json() if response.content else {}

    # -- 1. upload -----------------------------------------------------------

    def upload(
        self, path: Path, *, session_id: str, filename: str | None = None
    ) -> UploadedDocument:
        """Upload a document into a session, durably.

        Two things bite here.

        **The field is `file_base64`**, not `content_base64`. The wrong name returns a
        422 that names the missing field, which is genuinely helpful.

        **Without a `session_id` the upload is a one-off conversion and is not saved.**
        You get parsed HTML back and nothing is stored — and the response says so, in a
        `how_to_persist` field that states the exact request which would change it.
        That is the clearest piece of API self-documentation in this surface.
        """
        response = self._request(
            "POST",
            "/documents/upload-base64",
            json_body={
                "filename": filename or path.name,
                "file_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                "session_id": session_id,
            },
        )

        if not response.get("persisted"):
            raise SuperDocsError(
                f"{path.name} was not persisted despite a session_id. "
                f"Server said: {response.get('how_to_persist')!r}"
            )

        # The upload response does not carry the id chat needs; that comes from the
        # session's document list, where ids are session-scoped ("doc_primary") and
        # separate from the durable UUID.
        listed = self.list_documents(session_id)
        match = next(
            (d for d in listed if d.filename.startswith(Path(path.name).stem)), None
        ) or (listed[-1] if listed else None)

        if match is None:
            raise SuperDocsError(f"{path.name} uploaded but is not listed in the session")

        match.version_id = response.get("version_id")
        match.chunks_count = response.get("chunks_count", match.chunks_count)
        return match

    def list_documents(self, session_id: str) -> list[UploadedDocument]:
        response = self._request("GET", f"/sessions/{session_id}/documents")
        return [
            UploadedDocument(
                session_id=session_id,
                document_id=d["document_id"],
                durable_document_id=d.get("durable_document_id"),
                filename=d.get("title") or d["document_id"],
                chunks_count=d.get("chunks_count", 0),
            )
            for d in response.get("documents", [])
        ]

    # -- 2. chat -------------------------------------------------------------

    def chat(
        self,
        *,
        session_id: str,
        message: str,
        document_id: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
    ) -> ChatResult:
        """Send an edit instruction and wait for the job to settle.

        Async, always — and not only because long edits exceed the sync gateway
        timeout. **Sync `/v1/chat` never returns a `job_id`, and `/approve` requires
        one.** So with `approval_mode: ask_every_time`, sync chat produces changes that
        cannot be approved through the API at all. Async is the only path that closes
        the loop.

        `session_id` is caller-chosen, which makes it an idempotency handle: re-sending
        under the same session continues that conversation rather than starting a new one.

        `document_html` is deliberately never sent. The session already holds the
        document; re-sending it every turn is wasteful and risks clobbering edits the
        model has already made.
        """
        body: dict[str, Any] = {
            "session_id": session_id,
            "message": message,
            "approval_mode": approval_mode,
        }
        if document_id:
            body["document_id"] = document_id
        if model_tier:
            body["model_tier"] = model_tier
        if thinking_depth:
            body["thinking_depth"] = thinking_depth

        started = self._request("POST", "/chat/async", json_body=body)
        job_id = started.get("job_id")
        if not job_id:
            raise SuperDocsError(f"/chat/async returned no job_id: {sorted(started)}")

        return self.wait_for_job(job_id, session_id=session_id)

    def wait_for_job(self, job_id: str, *, session_id: str) -> ChatResult:
        """Poll a job until it stops moving.

        A quiet minute here is normal, not a hang — the brief is explicit that thirty
        seconds to several minutes with no visible progress is still processing. The
        ceiling exists so an automated run cannot block forever.
        """
        deadline = time.monotonic() + POLL_CEILING_SECONDS

        while True:
            job = self._request("GET", f"/jobs/{job_id}")
            status = (job.get("status") or "").lower()

            if status in TERMINAL_STATUSES or job.get("error"):
                break
            if time.monotonic() > deadline:
                raise SuperDocsError(
                    f"job {job_id} still {status!r} after {POLL_CEILING_SECONDS:.0f}s"
                )
            time.sleep(POLL_INTERVAL_SECONDS)

        if job.get("error"):
            raise SuperDocsError(f"job {job_id} failed: {job['error']}")

        # Pending changes live in `metadata`, not in `result` — `result` stays null for
        # the whole time the job is awaiting approval, which is exactly when a caller
        # needs the changes in order to act on them.
        metadata = job.get("metadata") or {}
        raw_changes = metadata.get("pending_changes") or []

        return ChatResult(
            session_id=session_id,
            job_id=job_id,
            status=(job.get("status") or "").lower(),
            pending_changes=[PendingChange.from_api(c) for c in raw_changes],
            response_text=self._latest_response_text(metadata),
            raw=job,
        )

    @staticmethod
    def _latest_response_text(metadata: dict[str, Any]) -> str:
        entries = metadata.get("intermediate_responses") or []
        spoken = [e for e in entries if e.get("type") == "user_facing"]
        return spoken[-1].get("content", "") if spoken else ""

    # -- 3. approve ----------------------------------------------------------

    def approve(
        self,
        session_id: str,
        *,
        job_id: str,
        change_id: str | None = None,
        approved: bool = True,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """Approve or reject one proposed change.

        **`job_id` is required**, and that is not documented in the task brief — which
        mentions only the top-level `approved`. Omitting either gives a 422 that does
        at least name the missing fields.

        Note the field is `change_id`, singular. Batch decisions go in `changes` as
        `[{change_id, approved, feedback}]`, not in a `change_ids` list.
        """
        body: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if change_id:
            body["change_id"] = change_id
        if feedback:
            body["feedback"] = feedback
        return self._request("POST", f"/chat/{session_id}/approve", json_body=body)

    def decide_all(
        self, result: ChatResult, *, verdicts: dict[str, bool] | None = None
    ) -> list[dict[str, Any]]:
        """Decide every pending change individually.

        Per item rather than all-or-nothing, because the point of a review is that a
        reviewer can accept one change and reject another in the same pass. `verdicts`
        maps change_id → approved; anything unlisted defaults to approved.
        """
        verdicts = verdicts or {}
        outcomes = []
        for change in result.pending_changes:
            outcomes.append(
                self.approve(
                    result.session_id,
                    job_id=result.job_id,
                    change_id=change.change_id,
                    approved=verdicts.get(change.change_id, True),
                )
            )
        return outcomes

    def continue_session(self, session_id: str, *, job_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/chat/{session_id}/continue", json_body={"job_id": job_id}
        )

    def wait_until_idle(self, session_id: str, *, timeout: float = 300.0) -> None:
        """Block until the session has no active job.

        Approving returns 200 immediately, but the job is not finished at that moment —
        it goes on to actually apply the change. Send the next instruction too soon and
        the API answers 409 `session_busy`, which is correct behaviour and easy to trip
        over when you drive a session in a loop, as this build does.

        Credit where it is due: the 409 body is one of the most useful error messages
        on this API. It names the condition, lists the states that count as active, and
        gives three concrete remedies. Most of this method is just doing what it says.
        """
        deadline = time.monotonic() + timeout
        active = {"pending", "in_progress", "processing", "running", "queued"}

        while True:
            jobs = self._request("GET", f"/sessions/{session_id}/jobs").get("jobs", [])
            if not any((j.get("status") or "").lower() in active for j in jobs):
                return
            if time.monotonic() > deadline:
                raise SuperDocsError(
                    f"session {session_id} still has an active job after {timeout:.0f}s"
                )
            time.sleep(POLL_INTERVAL_SECONDS)

    # -- 4. export -----------------------------------------------------------

    def export(
        self, session_id: str, *, fmt: str = "markdown", destination: Path | None = None
    ) -> bytes:
        """Export the session's document, returning the file bytes.

        Three things differ from what the task brief's cheat-sheet says, and each is a
        separate 404 or crash if you follow the sheet:

          * the path is **`/v1/documents/export`**, not `/v1/export`
          * it takes a **`session_id`**, not a document id
          * markdown is spelled **`markdown`**, not `md`

        And the response is **the file itself, not JSON** — a client that calls
        `.json()` on it dies on the first byte. Returning bytes here rather than a dict
        is the honest shape.

        Exports do not cost operations, so this is the cheap way to checkpoint work.
        """
        if fmt not in EXPORT_FORMATS:
            raise SuperDocsError(
                f"unknown export format {fmt!r}; expected one of {sorted(EXPORT_FORMATS)}"
            )

        url = f"{self._base}/documents/export"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._key}"},
                    json={"session_id": session_id, "format": fmt},
                )
        except httpx.RequestError as exc:
            raise SuperDocsError(f"export unreachable: {type(exc).__name__}") from exc

        self.calls_made += 1
        if response.status_code >= 400:
            raise SuperDocsError(
                f"export -> HTTP {response.status_code}: "
                f"{self._redact(response.text[:400])}"
            )

        data = response.content
        if destination is not None:
            destination.write_bytes(data)
            logger.info("exported %s (%d bytes)", destination.name, len(data))
        return data

    # -- budget --------------------------------------------------------------

    def ops_remaining(self) -> int | None:
        """Promo operations left.

        Read from /v1/users/me/promotions because the documented alternative does not
        work: the `usage` block on chat responses is null, and /v1/users/me/usage
        rejects `sk_` keys with a 401. This is the only reliable spend meter.
        """
        for promo in self._request("GET", "/users/me/promotions").get("active", []):
            return promo.get("ops_remaining")
        return None

    def whoami(self) -> dict[str, Any]:
        return self._request("GET", "/agents/whoami")
