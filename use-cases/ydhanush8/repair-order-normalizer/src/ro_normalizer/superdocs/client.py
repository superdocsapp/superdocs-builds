"""SuperDocs API client.

Written against docs.superdocs.app, then corrected against the API itself. Where
the two disagree the measured behaviour wins, and the disagreement is recorded in
PROGRESS.md rather than quietly smoothed over. The verified request and response
shapes are in `docs/superdocs-integration.md`.

    upload   POST /v1/documents/upload-base64   filename, file_base64, session_id
    edit     POST /v1/chat/async                message, session_id, approval_mode
    poll     GET  /v1/jobs/{job_id}             status, result.document_changes
    approve  POST /v1/chat/{session_id}/approve job_id, approved
    export   POST /v1/documents/export          session_id, format

Two differences from the task document:

* It is **session-based**, not document-based. A session holds the document, so
  later turns send only the instruction.
* Editing is **asynchronous**. `/v1/chat/async` returns a `job_id` and the result
  appears on the job.

The human-in-the-loop approval the documentation describes does not happen.
`approval_mode` is accepted with any value and the job completes with each change
marked `auto_approved`. The gate in this build is therefore upstream: the
pipeline does not send a change a person should see first.

The task document warns that proposed-change content arrives as a JSON-encoded
string needing a second parse; the current documentation says the changes are
structured objects. `parse_proposed_content` handles both, so whichever is true
of the deployed API, the client works — and the wrong assumption cannot produce
the empty diff cards the task document warns about.
"""

from __future__ import annotations

import base64
import html
import time
import uuid

import httpx

from ro_normalizer.superdocs.editor import (
    DocumentRef,
    ProposedChange,
    ProposedChanges,
    parse_proposed_content,
)


class SuperDocsError(RuntimeError):
    """Names the cause and, where possible, the fix."""


class SuperDocsDocumentEditor:
    """The four-call contract against the real API.

    Operations cost money, so nothing here retries a call that already spent
    one. A request that errors out is not billed for the edit it never made.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.superdocs.app",
        timeout: float = 300.0,
        client: httpx.Client | None = None,
        poll_interval: float = 2.0,
        poll_timeout: float = 300.0,
    ) -> None:
        if not api_key:
            raise SuperDocsError(
                "SUPERDOCS_API_KEY is empty. Create a key in Settings → API Keys, "
                "or set EDITOR_BACKEND=mock to run without one."
            )
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._sessions: dict[str, str] = {}
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-Title": "Repair-Order Narrative Normalizer",
            },
        )

    # -- transport ----------------------------------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        return self._read(self._send("POST", path, payload), path)

    def _get(self, path: str) -> dict:
        return self._read(self._send("GET", path), path)

    def _send(self, method: str, path: str, payload: dict | None = None) -> httpx.Response:
        """One place where transport failures become explained ones.

        Every other failure here names the cause and the fix. A dropped
        connection used to come out as a bare `httpx.ConnectError` from three
        frames down, which tells someone halfway through a batch nothing about
        what to do next.
        """
        try:
            if method == "GET":
                return self._client.get(path)
            return self._client.post(path, json=payload)
        except httpx.RequestError as exc:
            raise SuperDocsError(
                f"{path}: the SuperDocs API could not be reached ({type(exc).__name__}). "
                "Check the network and SUPERDOCS_BASE_URL, or set EDITOR_BACKEND=mock "
                "to work offline."
            ) from exc

    def _read(self, response: httpx.Response, path: str) -> dict:
        if response.status_code == 401:
            raise SuperDocsError(
                f"{path}: unauthorised. Check SUPERDOCS_API_KEY in .env — it should start 'sk_'."
            )
        if response.status_code == 429:
            raise SuperDocsError(
                f"{path}: operation quota exhausted. Exports and downloads are free; "
                "edits are not. Check the usage block on a previous response."
            )
        if response.status_code >= 400:
            raise SuperDocsError(f"{path}: HTTP {response.status_code}: {response.text[:300]}")
        try:
            return response.json()
        except ValueError:
            return {"_raw": response.text}

    # -- the four calls -----------------------------------------------------

    def upload(self, filename: str, content: str) -> DocumentRef:
        session_id = str(uuid.uuid4())
        document_html = _as_html(content)

        # The documentation says `document_html`. The API answers 422 asking for
        # `filename` and `file_base64`. Measured, not assumed.
        body = self._post(
            "/v1/documents/upload-base64",
            {
                "filename": filename,
                "file_base64": base64.b64encode(document_html.encode()).decode(),
                "session_id": session_id,
            },
        )
        # The session is the handle for every later call; the upload id is kept
        # because export accepts either.
        self._sessions[session_id] = body.get("upload_id") or body.get("version_id") or ""
        return DocumentRef(document_id=session_id, filename=filename)

    def propose_edit(self, document_id: str, instruction: str) -> ProposedChanges:
        """Ask for a targeted edit and wait for it to reach a decision point.

        `approval_mode` is sent because the documentation says it holds the
        change for a person. It does not. Six values were tried against the live
        API — "manual", "review", "required", "always", "hitl", "approval" — and
        every one was accepted, every job reached `completed`, and every edit was
        applied without anyone approving it. It is still sent in case the
        behaviour is fixed or is plan-dependent, but it is not relied on: the
        pipeline gates by deciding what to send, not by approving afterwards.
        """
        job = self._post(
            "/v1/chat/async",
            {
                "message": instruction,
                "session_id": document_id,
                # A boolean is rejected with 422; the field wants a string.
                "approval_mode": "manual",
            },
        )
        job_id = job.get("job_id")
        if not job_id:
            raise SuperDocsError("/v1/chat/async returned no job_id")

        state = self._await_job(job_id)

        # Approval is granted per *job*, not per change: the endpoint wants a
        # `job_id` and a single `approved`, so the change id here is the job id.
        #
        # Where the changes themselves live, in preference order, measured
        # against a live completed job:
        #
        #   result.document_changes.changes   one entry per edit, each with
        #                                     old_html / new_html / chunk_id and
        #                                     a `status` — this is the useful one
        #   metadata.pending_changes          documented, but null in practice
        #   result.document_changes           the whole rewritten document under
        #                                     `updated_html`; the last resort
        #
        # The first version of this read `document_changes` directly and so
        # reported every edit as one change covering the entire document. The
        # granular array was there all along.
        document_changes = (state.get("result") or {}).get("document_changes") or {}
        pending = (
            (document_changes.get("changes") if isinstance(document_changes, dict) else None)
            or (state.get("metadata") or {}).get("pending_changes")
            or ([document_changes] if document_changes else [])
        )

        # The task document says this arrives JSON-encoded; the current docs say
        # it is already an object. Handle both — guessing wrong is what produces
        # diff cards where every field reads `undefined`.
        decoded = parse_proposed_content(pending)
        if isinstance(decoded, dict):
            decoded = [decoded]

        changes = [
            ProposedChange(
                change_id=job_id,
                section=str(item.get("section") or item.get("chunk_id") or "document"),
                before=str(item.get("before") or item.get("old_html")
                           or item.get("original_html") or ""),
                after=str(
                    item.get("after")
                    or item.get("new_html")
                    or item.get("html")
                    or item.get("updated_html")
                    or ""
                ),
            )
            for index, item in enumerate(decoded)
            if isinstance(item, dict)
        ]
        return ProposedChanges(document_id=document_id, changes=changes)

    def approve(self, document_id: str, change_ids: list[str]) -> int:
        """`change_ids` are job ids — approval is granted a job at a time.

        A job that already applied its change answers 400 "not awaiting
        approval". That is not a failure to report upward: the edit is in the
        document either way, and raising here would abort a batch over a
        difference in when the change landed. It is recorded in PROGRESS.md as
        an API finding instead.
        """
        approved = 0
        for job_id in dict.fromkeys(change_ids):
            try:
                self._post(
                    f"/v1/chat/{document_id}/approve", {"job_id": job_id, "approved": True}
                )
            except SuperDocsError as exc:
                if "not awaiting approval" not in str(exc):
                    raise
            approved += 1
        return approved

    def reject(self, document_id: str, change_ids: list[str], feedback: str = "") -> int:
        """Not part of the four-call minimum, but the other half of a gate.

        A gate that can only say yes is not a gate.
        """
        rejected = 0
        for job_id in dict.fromkeys(change_ids):
            self._post(
                f"/v1/chat/{document_id}/approve",
                {"job_id": job_id, "approved": False, "feedback": feedback},
            )
            rejected += 1
        return rejected

    def export(self, document_id: str, fmt: str = "markdown") -> str:
        """Exports do not cost operations, so this is the cheap way to confirm
        what actually landed in the document."""
        body = self._post(
            "/v1/documents/export", {"session_id": document_id, "format": fmt}
        )
        return body.get("_raw") or body.get("content") or body.get("html") or ""

    # -- waiting ------------------------------------------------------------

    def _await_job(self, job_id: str) -> dict:
        """Poll until the job reaches a decision point.

        The task document is explicit that a long silence is still processing
        rather than a crash: operations on large documents, or the deepest model
        settings, can take from thirty seconds to several minutes.
        """
        deadline = time.monotonic() + self._poll_timeout
        while True:
            state = self._get(f"/v1/jobs/{job_id}")
            status = state.get("status")

            if status in {"awaiting_approval", "completed"}:
                return state
            if status == "failed":
                raise SuperDocsError(
                    f"job {job_id} failed: {state.get('error') or 'no reason given'}"
                )
            if time.monotonic() > deadline:
                raise SuperDocsError(
                    f"job {job_id} still '{status}' after {self._poll_timeout:.0f}s. "
                    "Large documents can take minutes; raise SUPERDOCS_TIMEOUT_SECONDS "
                    "if this is expected."
                )
            time.sleep(self._poll_interval)


def _as_html(text: str) -> str:
    """The API takes documents, not plain text."""
    paragraphs = [
        f"<p>{html.escape(block.strip()).replace(chr(10), '<br>')}</p>"
        for block in text.split("\n\n")
        if block.strip()
    ]
    return "<html><body>" + "".join(paragraphs) + "</body></html>"
