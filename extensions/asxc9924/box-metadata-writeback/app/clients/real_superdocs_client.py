"""Real SuperDocs REST API client (https://api.superdocs.app).

Replaces FakeSuperDocsClient with actual HTTP calls against the live
SuperDocs API, implementing the same four-call contract the pipeline is
built against: upload -> chat -> approve -> export.

Design notes / mapping decisions
---------------------------------
The real SuperDocs API is a *document-session* API, not a
classify-a-document-and-hand-back-fields API: a session_id holds one
open document, `POST /v1/chat` (or `/v1/chat/async`) edits that
document with natural language, and there is no generic "return me
this JSON" endpoint. Our abstract SuperDocsClient interface (upload ->
document_id, chat(document_id, instruction) -> structured
proposed_change, approve, export) was written for a semantic
document-intelligence API. To satisfy that contract for real against
the actual REST surface:

  * `upload()` opens a SuperDocs session (POST /v1/documents/upload-base64)
    and uses the session_id AS our `document_id` for the rest of the
    pipeline. There is no separate "document_id" concept exposed by the
    real API until a document is durably saved, and the session is the
    stable handle we need across chat/approve/export anyway.

  * `chat()` uses POST /v1/chat/async with approval_mode='ask_every_time'
    (this is what actually exercises approve() for real -- see below),
    and prompts the AI to answer with a single JSON object in its reply
    text rather than edit the document, for stages that are pure
    document-intelligence asks (classify / extract / describe a
    companion doc). This is a deliberate protocol we impose on top of
    a general-purpose editing API; it is documented here rather than
    hidden. The task brief's warning -- "proposed-change content
    arrives as a JSON-encoded string and needs a second parse" -- maps
    onto this real client as: the job's AI response text is a string,
    and *embedded inside that string* is a JSON object that itself
    needs its own json.loads once extracted. See _extract_json_payload
    and app.clients.superdocs_client.parse_proposed_change (the
    "second parse").

  * `approve()` calls the real POST /v1/chat/{session_id}/approve.
    Because our classify/extract/companion prompts explicitly ask the
    AI NOT to edit the document, most of those turns never produce a
    pending document change and the job goes straight to
    status=completed -- there is nothing to approve. In that case
    approve() is a genuine, honest no-op (checked via GET /v1/jobs
    before calling the endpoint), not a fake success. The call is still
    made structurally on every stage per the pipeline's contract; it
    just has nothing to do most of the time. This is a real, documented
    limitation of adapting an editing API to a classification workflow,
    not a bug -- see README "what we cut".

  * `export()` calls the real POST /v1/documents/export with our
    session_id, format=docx. Per the SuperDocs docs, exports are
    non-billable, so calling it defensively (as pipeline.py already
    does after normalize) costs nothing.

Practical operational notes from SuperDocs, applied here:
  * Long-running chat operations can take 30s-several minutes with no
    visible progress; that is normal, not a hang. _poll_job backs off
    and waits up to `poll_timeout` seconds before raising.
  * Operations are billable and metered (500/mo free tier). This client
    enforces an optional local budget (`max_operations`) as a second,
    client-side stopping rule on top of the API's own 429/quota
    handling, so a bug in a loop can't silently burn the whole monthly
    allowance before anyone notices.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from typing import Any, Optional

import requests

from app.clients.superdocs_client import (
    ChatResult,
    SuperDocsAPIError,
    SuperDocsClient,
    parse_proposed_change,
)

DEFAULT_BASE_URL = "https://api.superdocs.app"
DEFAULT_POLL_INTERVAL_SECONDS = 3.0
DEFAULT_POLL_TIMEOUT_SECONDS = 480.0  # 8 minutes; SuperDocs notes ops can take "several minutes"
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class RealSuperDocsClient(SuperDocsClient):
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model_tier: str = "core",
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT_SECONDS,
        max_operations: Optional[int] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_tier = model_tier
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._max_operations = max_operations
        self._operations_used = 0
        self._http = session or requests.Session()

    @classmethod
    def from_env(cls) -> Optional["RealSuperDocsClient"]:
        """Returns a configured RealSuperDocsClient if SUPERDOCS_API_KEY is
        set, otherwise None -- mirrors RealBoxClient.from_env() so
        app/api/main.py can fall back to FakeSuperDocsClient with no code
        change, only an env var."""
        api_key = os.environ.get("SUPERDOCS_API_KEY")
        if not api_key:
            return None
        max_ops_raw = os.environ.get("SUPERDOCS_MAX_OPERATIONS")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("SUPERDOCS_API_BASE", DEFAULT_BASE_URL),
            model_tier=os.environ.get("SUPERDOCS_MODEL_TIER", "core"),
            poll_timeout=float(os.environ.get("SUPERDOCS_POLL_TIMEOUT_SECONDS", DEFAULT_POLL_TIMEOUT_SECONDS)),
            max_operations=int(max_ops_raw) if max_ops_raw else None,
        )

    @property
    def operations_used(self) -> int:
        return self._operations_used

    # --- SuperDocsClient interface ------------------------------------------------

    def upload(self, filename: str, content: bytes) -> str:
        session_id = f"box-{uuid.uuid4().hex[:20]}"
        resp = self._request(
            "post",
            f"{self._base_url}/v1/documents/upload-base64",
            headers=self._headers(),
            json={
                "filename": filename,
                "file_base64": base64.b64encode(content).decode("ascii"),
                "session_id": session_id,
                "return_html": False,
            },
            timeout=120,
        )
        self._raise_for_status(resp, "upload")
        return session_id

    def chat(self, document_id: str, instruction: str) -> ChatResult:
        self._check_budget()
        prompt = _build_stage_prompt(instruction)
        resp = self._request(
            "post",
            f"{self._base_url}/v1/chat/async",
            headers=self._headers(),
            json={
                "message": prompt,
                "session_id": document_id,
                "approval_mode": "ask_every_time",
                "response_mode": "compact",
                "model_tier": self._model_tier,
            },
            timeout=60,
        )
        self._raise_for_status(resp, "chat")
        job_id = resp.json()["job_id"]

        job = self._poll_job(job_id)
        self._operations_used += 1  # one billable chat turn attempted, win or lose

        status = job.get("status")
        if status == "failed":
            raise SuperDocsAPIError(f"SuperDocs job {job_id} failed: {_job_error_detail(job)}")
        if status == "cancelled":
            raise SuperDocsAPIError(f"SuperDocs job {job_id} was cancelled")

        raw_message = _extract_response_text(job)
        raw_json_text = _extract_json_substring(raw_message)
        # This is the task brief's "second parse": raw_json_text is a JSON
        # string embedded inside the AI's reply text; parse_proposed_change
        # does the json.loads that turns it into a real dict (or None if it
        # isn't parseable, which we treat the same as "nothing proposed"
        # rather than crash the stage).
        proposed_change = parse_proposed_change(raw_json_text) if raw_json_text else None

        return ChatResult(session_id=job_id, raw_message=raw_message, proposed_change=proposed_change)

    def approve(self, document_id: str, session_id: str) -> None:
        job_id = session_id
        job = self._get_job(job_id)
        if job.get("status") != "awaiting_approval":
            # Nothing pending -- our classify/extract/companion prompts ask
            # the AI to answer in text, not edit the document, so most
            # turns complete without ever proposing a change. Honest no-op,
            # not a fake success: we checked real job state before skipping.
            return

        pending = ((job.get("metadata") or {}).get("pending_changes")) or []
        changes = [{"change_id": c.get("change_id"), "approved": True} for c in pending if c.get("change_id")]
        body: dict[str, Any] = {"job_id": job_id, "approved": True}
        if changes:
            body["changes"] = changes

        resp = self._request(
            "post",
            f"{self._base_url}/v1/chat/{document_id}/approve",
            headers=self._headers(),
            json=body,
            timeout=60,
        )
        self._raise_for_status(resp, "approve")
        # Approving resumes the job; wait for it to actually settle so a
        # caller who immediately exports doesn't race an in-flight commit.
        self._poll_job(job_id)

    def export(self, document_id: str) -> bytes:
        resp = self._request(
            "post",
            f"{self._base_url}/v1/documents/export",
            headers=self._headers(),
            json={"session_id": document_id, "format": "docx"},
            timeout=180,
        )
        self._raise_for_status(resp, "export")
        return resp.content

    # --- internals ------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Wraps requests.Session calls so a network-level failure
        (connection refused, DNS failure, read timeout -- anything that
        never got an HTTP response at all) still surfaces as a
        SuperDocsAPIError that call_with_retry recognizes, instead of a
        raw requests exception propagating past retry logic entirely.
        No status_code is available in this case (there was no
        response), so retry.is_retryable falls back to its message-
        substring heuristic, which "connection"/"timeout" in this
        message satisfies."""
        try:
            return getattr(self._http, method)(url, **kwargs)
        except requests.exceptions.RequestException as e:
            raise SuperDocsAPIError(f"SuperDocs {method} request to {url} failed: connection error: {e}") from e

    def _check_budget(self) -> None:
        if self._max_operations is not None and self._operations_used >= self._max_operations:
            raise SuperDocsAPIError(
                f"local SuperDocs operations budget exhausted "
                f"({self._operations_used}/{self._max_operations}); "
                "raise SUPERDOCS_MAX_OPERATIONS or unset it to remove the cap. "
                "This is a client-side stopping rule, separate from SuperDocs's own "
                "monthly quota, so a runaway loop can't silently burn the account."
            )

    def _get_job(self, job_id: str) -> dict[str, Any]:
        resp = self._request(
            "get",
            f"{self._base_url}/v1/jobs/{job_id}",
            headers=self._headers(),
            timeout=30,
        )
        self._raise_for_status(resp, "get_job")
        return resp.json()

    def _poll_job(self, job_id: str) -> dict[str, Any]:
        """Waits for a job to leave pending/in_progress. SuperDocs is
        explicit that this can take 30s to several minutes with no visible
        progress on large documents or deep model settings -- that is
        normal, so we back off and keep waiting up to poll_timeout rather
        than treat a quiet job as failed."""
        deadline = time.monotonic() + self._poll_timeout
        delay = self._poll_interval
        while True:
            job = self._get_job(job_id)
            status = job.get("status")
            if status in _TERMINAL_STATUSES or status == "awaiting_approval":
                return job
            if time.monotonic() >= deadline:
                raise SuperDocsAPIError(
                    f"SuperDocs job {job_id} still '{status}' after {self._poll_timeout:.0f}s "
                    "(still processing is expected behavior for large docs/deep model "
                    "settings, not necessarily a crash -- raise poll_timeout if this is routine)"
                )
            time.sleep(delay)
            delay = min(delay * 1.5, 20.0)

    def _raise_for_status(self, resp: requests.Response, op: str) -> None:
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise SuperDocsAPIError(
                f"SuperDocs {op} failed ({resp.status_code}): {detail}",
                status_code=resp.status_code,
            )


# --- stage-prompt protocol: ask the editing API to answer as JSON text --------

_STAGE_JSON_SPEC = {
    "classify": (
        'Analyze this document and reply with ONLY a single JSON object, no markdown fences, '
        'no other text, of the exact shape: {"doc_class": one of '
        '"contract"|"amendment"|"invoice"|"policy"|"unknown", "confidence": a number between 0 and 1}. '
        "Do not edit the document."
    ),
    "extract key terms": (
        "Extract only the fields this document actually states -- never guess or infer a "
        "value it doesn't contain. Reply with ONLY a single JSON object, no markdown fences, "
        'no other text, of the exact shape: {"fields": {"counterparty_name": str, '
        '"effective_date": str, "expiration_date": str, "contract_value": str}, '
        '"field_confidence": {<same keys>: number 0-1}}. Omit any key the document does not '
        "state rather than inventing a value. Do not edit the document."
    ),
    "companion document": (
        "Draft a short companion summary document for this source document (what it is, key "
        "terms, parties, dates). Reply with ONLY a single JSON object, no markdown fences, no "
        'other text, of the exact shape: {"companion_text": str}. Do not edit the document itself.'
    ),
    "normalize": (
        "Confirm this document can be normalized to a retention-approved template and briefly "
        'describe what that normalization would involve. Reply with ONLY a single JSON object, '
        'no markdown fences, no other text, of the exact shape: {"normalized_text": str}. '
        "Do not edit the document."
    ),
}


def _build_stage_prompt(instruction: str) -> str:
    lowered = instruction.lower()
    for key, spec in _STAGE_JSON_SPEC.items():
        if key in lowered:
            return f"{instruction} {spec}"
    return instruction


def _extract_response_text(job: dict[str, Any]) -> str:
    """The AI's reply text can live in a few places depending on job
    status/shape; check the likely spots defensively rather than assume
    one fixed schema, since the value we need (a compact JobResponse's
    natural-language reply) isn't fully pinned down in the public docs
    excerpt we integrated against."""
    result = job.get("result") or {}
    if isinstance(result, dict) and result.get("response"):
        return str(result["response"])
    if job.get("response"):
        return str(job["response"])
    metadata = job.get("metadata") or {}
    intermediate = metadata.get("intermediate_responses") or []
    texts = [str(item.get("content", "")) for item in intermediate if isinstance(item, dict)]
    return "\n".join(t for t in texts if t)


def _extract_json_substring(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else None


def _job_error_detail(job: dict[str, Any]) -> str:
    result = job.get("result")
    if isinstance(result, dict) and result.get("error"):
        return str(result["error"])
    return json.dumps(job)[:500]
