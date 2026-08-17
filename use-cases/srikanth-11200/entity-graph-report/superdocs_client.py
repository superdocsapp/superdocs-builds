"""
Thin async REST client for the real SuperDocs API - the assignment's
stated minimum contract (upload, chat, approve, export), plus job polling
for the async/HITL flow and image upload for the diagram.

Every endpoint path, HTTP method, and field name below traces to an exact
quoted excerpt independently verified against the raw, complete text of
docs.superdocs.app/llms-full.txt (fetched directly, not through a
summarizing tool, and grepped for byte-exact confirmation). Nothing here
is guessed from generic REST conventions or invented to fill a gap;
anywhere the confirmed docs did not specify a detail, this client does
not assume one (see each method's docstring for what is/isn't confirmed).

Adapted from the private DocTask (Task 1) repository's
app/integrations/superdocs_client.py for this standalone, public Task 2
package - the only change is from_settings(), which now reads
SUPERDOCS_API_KEY / SUPERDOCS_BASE_URL directly from the environment
instead of DocTask's own Settings object. No other behavior changed.

Endpoint choices, and why:

- Upload goes through POST /v1/documents/upload-base64 ({filename,
  file_base64, session_id}), not the plain multipart POST
  /v1/documents/upload - upload-base64 is the one confirmed to produce
  "chunk-ID structural editing," which the graph-driven, per-section
  design (this build's whole point) actually needs.
- The HITL approve flow uses POST /v1/chat/async + GET /v1/jobs/{job_id}
  polling, never the SSE stream. Confirmed: on the polling path,
  metadata.pending_changes is already a parsed list of dicts (two
  independent worked examples in the docs access it directly, e.g.
  `changes = job["metadata"]["pending_changes"]`, no json.loads call) -
  the JSON-stringified, double-parse-required proposed_change_batch.content
  field is specifically an SSE wire-format artifact
  (`event.data` -> parse -> `.content` -> parse again), not something the
  polling path ever exposes. parse_proposed_change_batch() below still
  implements that exact double-parse correctly and defensively, for
  completeness and for any future caller that does read the SSE stream
  directly - this client's own poll-based flow simply never needs to call
  it, because GET /v1/jobs/{job_id} never hands back a doubly-encoded
  string in the first place.
- Long-running chat always goes through /v1/chat/async + polling, never
  a longer synchronous timeout on plain POST /v1/chat - confirmed, sync
  /v1/chat hits a ~300s platform gateway timeout on long turns; this
  client relies on that documented async/polling mechanism instead of
  trying to out-wait the gateway.

Never logs the Authorization header, the raw API key, or full request/
response bodies (which may carry real document content) - only method,
path, and status code.
"""

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Confirmed exact host across every curl/Python/JS example in the docs
# (e.g. "curl -X POST https://api.superdocs.app/v1/chat ...").
DEFAULT_BASE_URL = "https://api.superdocs.app"

# This client's own bound on a single HTTP call - deliberately NOT an
# attempt to out-wait the ~300s sync-chat gateway timeout (see module
# docstring): every call this client makes is either fast by design
# (upload, start_chat_async, get_job, approve) or a bounded export, so a
# generous-but-finite timeout is the right default; long AI processing
# time is handled by polling, not by a longer single-request timeout.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0

# This client's own bound on the poll loop - not a documented SuperDocs
# limit. Prevents polling forever if a job never leaves pending/
# in_progress.
DEFAULT_MAX_POLL_WAIT_SECONDS = 600.0
DEFAULT_POLL_INTERVAL_SECONDS = 3.0


class SuperDocsConfigurationError(RuntimeError):
    """Raised when SUPERDOCS_API_KEY is not set in the environment."""


class SuperDocsAPIError(RuntimeError):
    """
    Raised for any non-2xx SuperDocs response. Carries the confirmed
    error shape: every SuperDocs error is JSON `{"detail": "..."}`
    (docs.superdocs.app/errors/error-codes), EXCEPT infrastructure-level
    429s (traffic surge) and the ~32 MiB gateway body-size rejection,
    both of which are documented as plain text/HTML, never JSON - this
    class never assumes a JSON body is present, it falls back to the raw
    response text when the content-type isn't JSON.
    """

    def __init__(self, status_code: int, detail: str, *, retry_after_seconds: float | None = None):
        self.status_code = status_code
        self.detail = detail
        # Confirmed: application-level 429s always carry a Retry-After
        # header (seconds). Infrastructure 429s carry none - stays None.
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"SuperDocs API error {status_code}: {detail}")


def parse_proposed_change_batch(raw_content: str | dict | list) -> Any:
    """
    Confirmed from docs.superdocs.app/llms-full.txt: the SSE
    `proposed_change_batch` event's `content` field is delivered as a
    JSON-stringified string, not a parsed object - "the content field
    inside it is a second layer of JSON that must be parsed again ...
    Missing the second parse is the single most common reason integrators
    see empty diff cards ... every field reads as undefined."

    Pure, no I/O. Defensive rather than assuming its input is always a
    raw string: an already-parsed dict/list is returned unchanged instead
    of being double-parsed again (which would raise on a non-string
    input to json.loads). Raises TypeError for anything else, and lets a
    malformed JSON string's json.JSONDecodeError propagate rather than
    swallowing it - a caller passing genuinely malformed data should see
    that loudly, not silently get None.
    """

    if isinstance(raw_content, (dict, list)):
        return raw_content
    if not isinstance(raw_content, str):
        raise TypeError(
            "Expected proposed_change_batch content to be a JSON string "
            f"or an already-parsed object, got {type(raw_content).__name__}."
        )
    return json.loads(raw_content)


class SuperDocsClient:
    """
    Thin async wrapper around the real SuperDocs REST API. See module
    docstring for the confirmed contract each method implements.
    """

    def __init__(
        self,
        api_key: str | None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ):
        if not api_key:
            raise SuperDocsConfigurationError(
                "SUPERDOCS_API_KEY is not set in the environment."
            )

        self._base_url = base_url.rstrip("/")
        # Confirmed header format: "Authorization: Bearer sk_YOUR_API_KEY"
        # (same format for REST and MCP; lce_ organization keys work
        # identically). Stored only in this header dict - never logged.
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout_seconds

    @classmethod
    def from_settings(cls) -> "SuperDocsClient":
        """
        Standalone-package equivalent of DocTask's from_settings():
        reads SUPERDOCS_API_KEY / SUPERDOCS_BASE_URL directly from the
        environment (no DocTask Settings object, no .env parsing) - the
        only behavioral difference from the private repo's version of
        this file.
        """

        api_key = os.environ.get("SUPERDOCS_API_KEY")
        base_url = os.environ.get("SUPERDOCS_BASE_URL") or DEFAULT_BASE_URL
        return cls(api_key=api_key, base_url=base_url)

    # -- low-level request/error handling --------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"

        logger.info("SuperDocs %s %s", method, path)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(method, url, headers=self._headers, json=json_body)

        if response.status_code >= 400:
            raise self._error_from_response(response)

        return response

    @staticmethod
    def _error_from_response(response: httpx.Response) -> SuperDocsAPIError:
        retry_after = response.headers.get("Retry-After")
        retry_after_seconds = float(retry_after) if retry_after else None

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
        else:
            # Confirmed: infrastructure 429s and the platform gateway's
            # own body-size rejection return plain text/HTML - never
            # parsed as JSON.
            detail = response.text

        return SuperDocsAPIError(
            response.status_code, detail, retry_after_seconds=retry_after_seconds
        )

    # -- the four operations, plus job polling ----------------------------

    async def upload_document(
        self, *, filename: str, content: bytes, session_id: str
    ) -> dict[str, Any]:
        """
        POST /v1/documents/upload-base64 - confirmed request fields:
        filename, file_base64, session_id.

        The response schema beyond session_id (which the caller already
        supplied, not something the server generates) was not
        independently confirmed - this method deliberately returns the
        raw parsed response dict without asserting on or depending on
        any specific field, so it never relies on an unconfirmed schema.
        """

        file_base64 = base64.b64encode(content).decode("ascii")
        response = await self._request(
            "POST",
            "/v1/documents/upload-base64",
            json_body={
                "filename": filename,
                "file_base64": file_base64,
                "session_id": session_id,
            },
        )
        return response.json()

    async def start_chat_async(
        self,
        *,
        session_id: str,
        message: str,
        approval_mode: str = "ask_every_time",
    ) -> str:
        """
        POST /v1/chat/async - confirmed request fields used here:
        message, session_id, approval_mode. document_html is
        deliberately never sent: confirmed that once a session holds a
        document (from upload_document above), the server persists it
        across turns, so it must be omitted on follow-up calls, not
        re-sent. Returns job_id (confirmed field on the response).
        """

        response = await self._request(
            "POST",
            "/v1/chat/async",
            json_body={
                "session_id": session_id,
                "message": message,
                "approval_mode": approval_mode,
            },
        )
        return response.json()["job_id"]

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """
        GET /v1/jobs/{job_id} - confirmed status values: pending,
        in_progress, awaiting_approval, completed, failed, cancelled.
        Confirmed: on awaiting_approval, metadata.pending_changes carries
        the proposed changes as an already-parsed list (see module
        docstring) and metadata.awaiting_kind distinguishes a HITL change
        review from a large-edit continue_prompt pause.
        """

        response = await self._request("GET", f"/v1/jobs/{job_id}")
        return response.json()

    async def poll_job_until_done(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_wait_seconds: float = DEFAULT_MAX_POLL_WAIT_SECONDS,
    ) -> dict[str, Any]:
        """
        Polls GET /v1/jobs/{job_id} until status leaves pending/
        in_progress (i.e. becomes awaiting_approval, completed, failed,
        or cancelled) - the documented async/polling mechanism, used
        here instead of ever assuming a longer synchronous request
        timeout (see module docstring).

        max_wait_seconds/poll_interval_seconds are this client's own
        bounds, not documented SuperDocs limits - raises TimeoutError if
        exceeded rather than polling forever.
        """

        deadline = time.monotonic() + max_wait_seconds

        while True:
            job = await self.get_job(job_id)

            if job.get("status") not in ("pending", "in_progress"):
                return job

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"SuperDocs job {job_id} did not leave pending/in_progress "
                    f"within {max_wait_seconds}s."
                )

            await asyncio.sleep(poll_interval_seconds)

    async def approve_all_pending_changes(
        self,
        *,
        session_id: str,
        job_id: str,
        pending_changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        POST /v1/chat/{session_id}/approve - confirmed request shape:
        {job_id, approved, changes: [{change_id, approved, feedback?}]}.
        The top-level `approved` is required even for a batch decision -
        confirmed: omitting it is rejected with a generic 422 - so it is
        always sent here, alongside per-change approved=true for every
        entry in pending_changes. This method approves every pending
        change; no per-section rejection logic is in this scope.
        """

        response = await self._request(
            "POST",
            f"/v1/chat/{session_id}/approve",
            json_body={
                "job_id": job_id,
                "approved": True,
                "changes": [
                    {"change_id": change["change_id"], "approved": True}
                    for change in pending_changes
                ],
            },
        )
        return response.json()

    async def upload_image(self, *, content: bytes) -> dict[str, Any]:
        """
        POST /v1/documents/images/upload-base64 - confirmed request field:
        image_base64 (raw base64, no data: URL prefix - this method
        supplies plain base64 explicitly, since the docs confirm both
        forms are accepted and a bare base64 string is simplest). Confirmed
        constraints: PNG/JPEG/WebP/GIF/SVG, up to 10 MB decoded; does NOT
        require session_id (unlike document/attachment uploads - this is
        deliberately a separate, session-independent asset).

        Returns "a stable public URL to embed in a document via
        <img src=...>" per the docs, but the exact response field name
        holding that URL was not independently confirmed (no worked JSON
        example was found) - this method deliberately returns the raw
        parsed response dict without asserting on a specific field.
        Callers must resolve the URL field themselves (see
        report_to_superdocs.resolve_uploaded_image_url) rather than this
        client guessing a key name it never confirmed.
        """

        if len(content) > 10 * 1024 * 1024:
            raise ValueError(
                f"Image is {len(content)} bytes, exceeding the confirmed "
                "10 MB decoded limit for POST "
                "/v1/documents/images/upload-base64."
            )

        image_base64 = base64.b64encode(content).decode("ascii")
        response = await self._request(
            "POST",
            "/v1/documents/images/upload-base64",
            json_body={"image_base64": image_base64},
        )
        return response.json()

    async def export_document(self, *, session_id: str, format: str = "docx") -> bytes:
        """
        POST /v1/documents/export - confirmed request fields used here:
        session_id, format. format is one of the five confirmed values:
        docx (default), pdf, html, markdown, txt. Returns the raw binary
        file body (confirmed: "a binary file download with the
        appropriate Content-Type header").
        """

        response = await self._request(
            "POST",
            "/v1/documents/export",
            json_body={"session_id": session_id, "format": format},
        )
        return response.content
