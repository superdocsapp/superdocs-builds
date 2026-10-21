"""Idempotent, retried, traced wrapper around SuperDocs's core calls.

Only used by drafter/ (Task 2) and close_package/ (Task 2.2) — Task 1's pipeline
does not call SuperDocs at all (Task 1 is a standalone agentic system; see TASK.md's
"Task 1 vs Task 2" distinction).

Endpoint shapes are as documented in TASK.md, pulled from docs.superdocs.app and the
full llms-full.txt reference:
  - POST /v1/documents/upload   (multipart)
  - POST /v1/chat   (synchronous)
  - POST /v1/chat/async   (added for drafter/: returns a job_id immediately; see below)
  - GET  /v1/jobs/{job_id}   (added for drafter/: poll for status/result/pending_changes)
  - POST /v1/chat/{session_id}/approve   (top-level `approved` REQUIRED, even batch —
    see the llms-full.txt gotcha logged in TASK.md; omitting it -> generic 422)
  - POST /v1/documents/export

WHY chat_async/get_job WERE ADDED (not part of core/'s original Day-2 build):
llms-full.txt is explicit that human-in-the-loop approval (`approval_mode=
"ask_every_time"`) is only available on the ASYNC endpoint, not the synchronous
one, and calls it out as "required for regulated workflows (legal, medical,
compliance) where every AI edit must be reviewed before it touches the
document." A revenue recognition memo is exactly that kind of regulated
content -- and this mirrors Task 1's own human-gate philosophy (nothing
reaches a final, committed state without an explicit human decision). So
drafter/ uses the async+approval flow for the memo-authoring turn, not the
plain synchronous chat() this module already had.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Self

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.idempotency import IdempotencyStore
from core.logging import get_logger

logger = get_logger(__name__)

_TEXT_EXPORT_FORMATS = {"html", "markdown", "txt"}
_CONTENT_DISPOSITION_FILENAME_RE = re.compile(r'filename="([^"]+)"')


def _parse_filename(content_disposition: str) -> str:
    match = _CONTENT_DISPOSITION_FILENAME_RE.search(content_disposition)
    return match.group(1) if match else ""


class SuperDocsError(Exception):
    """Base error for SuperDocs API failures."""


class SuperDocsTransientError(SuperDocsError):
    """Retryable: network blip, 5xx, 429, timeout."""


class SuperDocsPermanentError(SuperDocsError):
    """Not retryable: 4xx validation error, bad request shape, missing config."""


def _classify(exc: httpx.HTTPStatusError) -> SuperDocsError:
    status = exc.response.status_code
    if status >= 500 or status == 429:
        return SuperDocsTransientError(f"{status}: {exc.response.text}")
    return SuperDocsPermanentError(f"{status}: {exc.response.text}")


class SuperDocsClient:
    """A thin wrapper around the four core SuperDocs calls. Idempotency is enforced
    client-side via IdempotencyStore (see core/idempotency.py for why); transient
    failures are retried with exponential backoff, permanent failures raise
    immediately and are never retried."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.superdocs.app",
        idempotency_store: IdempotencyStore | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise SuperDocsPermanentError("SuperDocs API key is required")
        self._store = idempotency_store
        self._client = http_client or httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            # Sync gateway times out ~300s per docs; give it headroom, not infinity.
            timeout=httpx.Timeout(30.0, read=300.0),
        )

    @retry(
        retry=retry_if_exception_type(SuperDocsTransientError),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _do_post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = self._client.post(path, **kwargs)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            classified = _classify(exc)
            logger.warning("superdocs_call_failed", path=path, error=str(classified))
            raise classified from exc
        except httpx.TransportError as exc:
            logger.warning("superdocs_transport_error", path=path, error=str(exc))
            raise SuperDocsTransientError(str(exc)) from exc
        return resp.json()  # type: ignore[no-any-return]

    @retry(
        retry=retry_if_exception_type(SuperDocsTransientError),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _do_get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = self._client.get(path, **kwargs)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            classified = _classify(exc)
            logger.warning("superdocs_call_failed", path=path, error=str(classified))
            raise classified from exc
        except httpx.TransportError as exc:
            logger.warning("superdocs_transport_error", path=path, error=str(exc))
            raise SuperDocsTransientError(str(exc)) from exc
        return resp.json()  # type: ignore[no-any-return]

    @retry(
        retry=retry_if_exception_type(SuperDocsTransientError),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _do_post_raw(self, path: str, **kwargs: Any) -> httpx.Response:
        """Like _do_post, but does NOT assume the response body is JSON --
        used only by export(). A REAL BUG THIS METHOD FIXES, caught via a
        real account call (2026-08-11), not a mock: /v1/documents/export's
        actual response is the raw exported file (Content-Type: text/html
        for format=html, application/vnd.openxmlformats...
        wordprocessingml.document for format=docx -- confirmed directly
        against the live API, never application/json). export() previously
        called resp.json() on this like every other endpoint, which would
        raise a JSON-decode error on every real call. Every existing test
        used httpx.MockTransport returning a JSON fixture (correct for
        every OTHER endpoint), which fully masked this -- exactly the kind
        of gap "tests that only prove your mocks work do not count"
        exists to catch."""
        try:
            resp = self._client.post(path, **kwargs)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            classified = _classify(exc)
            logger.warning("superdocs_call_failed", path=path, error=str(classified))
            raise classified from exc
        except httpx.TransportError as exc:
            logger.warning("superdocs_transport_error", path=path, error=str(exc))
            raise SuperDocsTransientError(str(exc)) from exc
        return resp

    def _post_idempotent(
        self, idem_key: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Check the idempotency store first; only hit the network on a real miss;
        record the result on success so a retry of the *caller* (not just a
        network-level retry, which _do_post already handles) is a provable no-op."""
        if self._store is not None:
            cached = self._store.get(idem_key)
            if cached is not None:
                logger.info("superdocs_idempotent_hit", idem_key=idem_key, path=path)
                return cached

        result = self._do_post(path, **kwargs)

        if self._store is not None:
            self._store.put(idem_key, result)

        return result

    def upload_document(
        self, file_path: str | Path, session_id: str, open_mode: str = "replace"
    ) -> dict[str, Any]:
        file_path = Path(file_path)
        idem_key = f"upload:{session_id}:{file_path.name}:{file_path.stat().st_size}"
        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f)}
            data = {"session_id": session_id, "open_mode": open_mode}
            return self._post_idempotent(
                idem_key, "/v1/documents/upload", files=files, data=data
            )

    def chat(
        self,
        message: str,
        session_id: str,
        document_html: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """request_id, if given, becomes the idempotency key — pass a stable id
        (e.g. derived from your own pipeline's step id) when you want a retried
        *caller* to be a no-op. Omit it for an intentionally new chat turn."""
        idem_key = request_id or f"chat:{session_id}:{uuid.uuid4()}"
        payload: dict[str, Any] = {"message": message, "session_id": session_id}
        if document_html is not None:
            payload["document_html"] = document_html
        return self._post_idempotent(idem_key, "/v1/chat", json=payload)

    def chat_async(
        self,
        message: str,
        session_id: str,
        document_html: str | None = None,
        approval_mode: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Starts a long-running or HITL-approved edit; returns {"job_id": ...}
        immediately -- poll get_job() for status/result. Pass approval_mode=
        "ask_every_time" to require a human decision on every proposed change
        before it's applied (see module docstring for why drafter/ uses this).

        NOT given a GET-based idempotent-hit shortcut the way the sync calls
        are: idempotency here still records the response (so a retried
        *caller* doesn't start a second, duplicate job for the same logical
        request), but the actual work happens server-side and asynchronously,
        so "no-op on retry" here means "don't start ANOTHER job," not "return
        instantly" -- the caller still has to poll get_job() either way."""
        idem_key = request_id or f"chat_async:{session_id}:{uuid.uuid4()}"
        payload: dict[str, Any] = {"message": message, "session_id": session_id}
        if document_html is not None:
            payload["document_html"] = document_html
        if approval_mode is not None:
            payload["approval_mode"] = approval_mode
        return self._post_idempotent(idem_key, "/v1/chat/async", json=payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Read-only -- never idempotency-cached (the whole point is reading
        CURRENT status, which changes over the job's lifetime; caching this
        would mean polling forever returns the first-ever snapshot). Returns
        status (pending/in_progress/awaiting_approval/completed/failed/
        cancelled), result once completed, and metadata.pending_changes while
        awaiting_approval."""
        return self._do_get(f"/v1/jobs/{job_id}")

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancels a pending or in-progress async job -- the concrete
        mechanism behind TASK.md's "build a small-sample mode + stopping rule
        early" gotcha for budget-constrained operations."""
        idem_key = f"cancel_job:{job_id}"
        return self._post_idempotent(idem_key, f"/v1/jobs/{job_id}/cancel")

    def approve(
        self,
        session_id: str,
        job_id: str,
        approved: bool,
        change_id: str | None = None,
        feedback: str | None = None,
        changes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # `approved` at the top level is REQUIRED even for batch shapes — logged as
        # a build-critical gotcha in TASK.md. Omitting it -> generic 422.
        idem_key = f"approve:{session_id}:{job_id}:{change_id or 'batch'}"
        payload: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if change_id is not None:
            payload["change_id"] = change_id
        if feedback is not None:
            payload["feedback"] = feedback
        if changes is not None:
            payload["changes"] = changes
        return self._post_idempotent(
            idem_key, f"/v1/chat/{session_id}/approve", json=payload
        )

    def export(
        self,
        session_id: str | None = None,
        html: str | None = None,
        format: str = "docx",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Returns {"content": ..., "content_type": ..., "filename": ...,
        "format": format}. `content` is `str` for text formats (html/
        markdown/txt) and `bytes` for binary ones (docx/pdf/doc) -- this
        reflects what the real API actually returns (see _do_post_raw's
        docstring), not a JSON envelope.

        Deliberately NOT idempotency-cached, unlike every other call here:
        the real response is raw file content, not a JSON-serializable
        value our Postgres-backed IdempotencyStore (a jsonb column) can
        hold, and binary content would need a whole separate storage path
        to cache meaningfully. Re-exporting unchanged content is cheap and
        safe on SuperDocs's own side too (per TASK.md's billing note:
        "already-satisfied requests bill 0"), so nothing meaningful is
        lost by not caching this client-side as well."""
        if not session_id and not html:
            raise SuperDocsPermanentError("export requires session_id or html")
        payload: dict[str, Any] = {"format": format}
        if session_id:
            payload["session_id"] = session_id
        if html:
            payload["html"] = html
        if options:
            payload["options"] = options

        resp = self._do_post_raw("/v1/documents/export", json=payload)
        content_type = resp.headers.get("content-type", "")
        filename = _parse_filename(resp.headers.get("content-disposition", ""))
        content: str | bytes = resp.text if format in _TEXT_EXPORT_FORMATS else resp.content
        return {
            "content": content,
            "content_type": content_type,
            "filename": filename,
            "format": format,
        }

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
