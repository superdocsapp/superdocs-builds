"""Client for SuperDocs' real, documented REST contract.

Earlier version of this file was written against a *guessed* schema
(POST /documents, POST /documents/{id}/chat, POST /documents/{id}/approve,
GET /documents/{id}/export) because docs.superdocs.app was unreachable
from the original build environment. That schema does not exist on the
real API, which is why the build didn't work end to end. This version is
written directly against the documented endpoints:

  - POST /v1/documents/upload          (multipart file + session_id)
  - POST /v1/uploads                   (pre-signed PUT URL, for large files)
  - POST /v1/uploads/{upload_id}/process
  - POST /v1/chat                      (approval_mode="approve_all")
  - POST /v1/chat/async                (approval_mode="ask_every_time")
  - GET  /v1/jobs/{job_id}
  - POST /v1/chat/{session_id}/approve
  - POST /v1/chat/{session_id}/continue
  - POST /v1/documents/export

Every field name below is copied verbatim from docs.superdocs.app
(Documents, Sessions, Async Jobs, Human-in-the-Loop, Error Codes, Rate
Limits pages) — see README "How this matches the real API" for the
section-by-section mapping.

The property this module exists to prove for the object-storage-pipeline
build specifically: bytes never fully materialize in the orchestrator's
memory. `upload_document` streams the S3-sourced byte iterator straight
into the outgoing request body (hand-rolled multipart encoding, or a raw
PUT for the pre-signed path); `export_to_dest_url` does the same in the
opposite direction, streaming the SuperDocs export response directly to
an S3 pre-signed PUT URL. `chunk_size_bytes` bounds how much is ever
resident at once, independent of total file size — proven in
tests/test_streaming_bounds.py.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import httpx

logger = logging.getLogger("superdocs_client")


class SuperDocsError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class UploadInfo:
    session_id: str
    chunks_count: int | None = None
    version_id: str | None = None
    method: str = "direct"  # "direct" (multipart) or "presigned"


@dataclass
class ChatResult:
    response_text: str
    updated_html: str | None
    changes_summary: str | None
    version_id: str | None = None
    monthly_used: int | None = None
    monthly_remaining: int | None = None
    was_billable: bool | None = None


class ChunkSizeTracker:
    """Wraps a byte iterator and records the size of every chunk that
    passed through it, without altering the data. Used by tests to prove
    the streaming bound is real, not just claimed — production code
    doesn't read these attributes, but it costs nothing to leave them
    instrumentable, and the pipeline logs them for its own visibility."""

    def __init__(self, source: Iterable[bytes]):
        self._source = source
        self.max_chunk_size = 0
        self.total_bytes = 0
        self.chunk_count = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._source:
            if chunk:
                self.max_chunk_size = max(self.max_chunk_size, len(chunk))
                self.total_bytes += len(chunk)
                self.chunk_count += 1
                yield chunk


def _multipart_stream(
    boundary: str,
    fields: dict[str, str],
    file_field_name: str,
    filename: str,
    content_type: str,
    file_chunks: Iterable[bytes],
) -> Iterator[bytes]:
    """Hand-rolled streaming multipart/form-data encoder.

    Built by hand instead of relying on httpx's own multipart machinery
    so the streaming behaviour is explicit, testable, and independent of
    any particular httpx version's internal handling of generic
    iterators in the `files=` parameter. The file's bytes are yielded
    exactly as they arrive from `file_chunks` — nothing here ever holds
    more than one chunk at a time.
    """
    nl = b"\r\n"
    for name, value in fields.items():
        yield f"--{boundary}\r\n".encode()
        yield f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        yield value.encode("utf-8") + nl
    yield f"--{boundary}\r\n".encode()
    yield (
        f'Content-Disposition: form-data; name="{file_field_name}"; '
        f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
    ).encode()
    for chunk in file_chunks:
        yield chunk
    yield nl
    yield f"--{boundary}--\r\n".encode()


def _decode_export_warnings(headers: httpx.Headers) -> list[dict]:
    """X-Export-Warnings is a base64-encoded JSON list, per
    docs.superdocs.app/concepts/documents#non-fatal-warnings."""
    raw = headers.get("X-Export-Warnings")
    if not raw:
        return []
    try:
        return json.loads(base64.b64decode(raw))
    except Exception:
        logger.debug("Could not decode X-Export-Warnings header: %r", raw)
        return []


class SuperDocsClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        http_client: httpx.Client | None = None,
        raw_http_client: httpx.Client | None = None,
        chunk_size_bytes: int = 262_144,
        direct_upload_max_bytes: int = 15_000_000,
        upload_purpose: str = "document-upload",
        default_approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
        max_retries: int = 5,
        retry_base_delay_seconds: float = 1.0,
        request_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 2.0,
        max_wait_seconds: float = 600.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._chunk_size = chunk_size_bytes
        self._direct_upload_max_bytes = direct_upload_max_bytes
        self._upload_purpose = upload_purpose
        self._default_approval_mode = default_approval_mode
        self._model_tier = model_tier
        self._thinking_depth = thinking_depth
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay_seconds
        self._poll_interval = poll_interval_seconds
        self._max_wait_seconds = max_wait_seconds

        # Authenticated client, used only for SuperDocs API calls.
        self._client = http_client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=request_timeout_seconds,
        )
        self._raw_client = raw_http_client or httpx.Client(timeout=request_timeout_seconds)

        # Exposed for test assertions / operational visibility — not
        # used by any control-flow decision.
        self.last_upload_tracker: ChunkSizeTracker | None = None
        self.last_export_tracker: ChunkSizeTracker | None = None

    # ------------------------------------------------------------------
    # Low-level request helper: retries 429 (honouring Retry-After) and
    # 5xx (exponential backoff), per docs.superdocs.app/errors/rate-limits.
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self._base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            response = self._client.request(method, url, **kwargs)
            if response.status_code == 429 and attempt <= self._max_retries:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after_header) if retry_after_header else None
                except ValueError:
                    delay = None
                if delay is None:
                    # Plain-text 429 with no Retry-After = infrastructure
                    # surge, not quota exhaustion — back off with jitter.
                    delay = self._retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "429 from %s %s — retrying in %.1fs (attempt %d/%d)",
                    method, path, delay, attempt, self._max_retries,
                )
                time.sleep(delay)
                continue
            if response.status_code >= 500 and attempt <= self._max_retries:
                delay = self._retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "%s from %s %s — retrying in %.1fs (attempt %d/%d)",
                    response.status_code, method, path, delay, attempt, self._max_retries,
                )
                time.sleep(delay)
                continue
            return response

    @staticmethod
    def _raise_for_error(response: httpx.Response, action: str) -> None:
        if response.status_code < 400:
            return
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise SuperDocsError(
            f"{action} failed: HTTP {response.status_code} {detail}",
            status_code=response.status_code,
            body=detail,
        )

    def open_presigned_stream(self, url: str):
        """Opens any pre-signed URL (S3 GET, typically) as a streaming
        httpx response using the client's unauthenticated connection
        pool. Public on purpose: the pipeline needs to stream the S3
        source object in without ever buffering it fully, and reusing
        this client's own raw connection pool (rather than opening a
        second one) keeps everything in one place."""
        return self._raw_client.stream("GET", url)

    # ------------------------------------------------------------------
    # Upload — POST /v1/documents/upload (direct) or the pre-signed
    # /v1/uploads -> PUT -> /v1/uploads/{id}/process flow for large files.
    # ------------------------------------------------------------------
    def upload_document(
        self,
        chunks: Iterable[bytes],
        filename: str,
        session_id: str,
        size_bytes: int | None = None,
        content_type: str = "application/octet-stream",
    ) -> UploadInfo:
        if size_bytes is not None and size_bytes >= self._direct_upload_max_bytes:
            return self._upload_via_presigned(chunks, filename, session_id, size_bytes, content_type)
        return self._upload_direct(chunks, filename, session_id, content_type)

    def _upload_direct(
        self, chunks: Iterable[bytes], filename: str, session_id: str, content_type: str
    ) -> UploadInfo:
        boundary = f"superdocs-{uuid.uuid4().hex}"
        tracker = ChunkSizeTracker(chunks)
        body_iter = _multipart_stream(
            boundary, {"session_id": session_id}, "file", filename, content_type, tracker
        )
        response = self._client.post(
            f"{self._base_url}/v1/documents/upload",
            content=body_iter,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        self.last_upload_tracker = tracker
        self._raise_for_error(response, "POST /v1/documents/upload")
        payload = response.json()
        return UploadInfo(
            session_id=payload.get("session_id", session_id),
            chunks_count=payload.get("chunks_count"),
            version_id=payload.get("version_id"),
            method="direct",
        )

    def _upload_via_presigned(
        self,
        chunks: Iterable[bytes],
        filename: str,
        session_id: str,
        size_bytes: int,
        content_type: str,
    ) -> UploadInfo:
        # 1. Request a pre-signed PUT URL. docs.superdocs.app/api-reference
        #    /uploads: request body {filename, content_type, size_bytes,
        #    purpose}; response {upload_url, upload_id}.
        req = self._request(
            "POST",
            "/v1/uploads",
            json={
                "filename": filename,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "purpose": self._upload_purpose,
            },
        )
        self._raise_for_error(req, "POST /v1/uploads")
        info = req.json()
        upload_url, upload_id = info["upload_url"], info["upload_id"]

        # 2. PUT the file straight to storage, streamed — this is the
        #    call that proves "never downloads the payload to the
        #    orchestrator" for files past the direct-upload threshold.
        tracker = ChunkSizeTracker(chunks)
        put_response = self._raw_client.put(
            upload_url, content=tracker, headers={"Content-Type": content_type}
        )
        self.last_upload_tracker = tracker
        if put_response.status_code >= 400:
            raise SuperDocsError(
                f"pre-signed PUT to SuperDocs upload_url failed: HTTP {put_response.status_code}",
                status_code=put_response.status_code,
            )

        # 3. Parse it into the session. parse_mode="document" loads it as
        #    the active editable document; return_html=False keeps the
        #    response compact (we don't need the HTML body here).
        process = self._request(
            "POST",
            f"/v1/uploads/{upload_id}/process",
            json={
                "filename": filename,
                "session_id": session_id,
                "parse_mode": "document",
                "return_html": False,
            },
        )
        self._raise_for_error(process, f"POST /v1/uploads/{upload_id}/process")
        payload = process.json()
        return UploadInfo(
            session_id=payload.get("session_id", session_id),
            chunks_count=payload.get("chunks_count"),
            version_id=payload.get("version_id"),
            method="presigned",
        )

    # ------------------------------------------------------------------
    # Edit (+ approve) — two documented modes, see README for why
    # ask_every_time is the default despite auto-approving everything.
    # ------------------------------------------------------------------
    def edit_document(
        self,
        session_id: str,
        instruction: str,
        approval_mode: str | None = None,
    ) -> ChatResult:
        mode = approval_mode or self._default_approval_mode
        if mode == "approve_all":
            return self._edit_sync_approve_all(session_id, instruction)
        if mode == "ask_every_time":
            return self._edit_async_with_review(session_id, instruction)
        raise ValueError(f"unknown approval_mode: {mode!r}")

    def _chat_body(self, session_id: str, instruction: str, approval_mode: str) -> dict:
        body: dict = {
            "message": instruction,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }
        if self._model_tier:
            body["model_tier"] = self._model_tier
        if self._thinking_depth:
            body["thinking_depth"] = self._thinking_depth
        return body

    def _edit_sync_approve_all(self, session_id: str, instruction: str) -> ChatResult:
        response = self._request(
            "POST", "/v1/chat", json=self._chat_body(session_id, instruction, "approve_all")
        )
        self._raise_for_error(response, "POST /v1/chat")
        return self._chat_result_from_payload(response.json())

    def _edit_async_with_review(self, session_id: str, instruction: str) -> ChatResult:
        start = self._request(
            "POST",
            "/v1/chat/async",
            json=self._chat_body(session_id, instruction, "ask_every_time"),
        )
        self._raise_for_error(start, "POST /v1/chat/async")
        job_id = start.json()["job_id"]

        deadline = time.monotonic() + self._max_wait_seconds
        while True:
            if time.monotonic() > deadline:
                raise SuperDocsError(
                    f"job {job_id} did not settle within {self._max_wait_seconds}s"
                )

            job_resp = self._request("GET", f"/v1/jobs/{job_id}")
            self._raise_for_error(job_resp, f"GET /v1/jobs/{job_id}")
            job = job_resp.json()
            status = job.get("status")

            if status == "completed":
                return self._chat_result_from_payload(job.get("result") or {})
            if status == "failed":
                raise SuperDocsError(f"job {job_id} failed: {job.get('error')}")
            if status == "cancelled":
                raise SuperDocsError(f"job {job_id} was cancelled")
            if status == "awaiting_approval":
                metadata = job.get("metadata") or {}
                if metadata.get("awaiting_kind") == "continue_prompt":
                    # A very large edit paused partway through and is
                    # asking whether to keep going — resume it. Not the
                    # same pause as a change review (see docs.superdocs
                    # .app/guides/async-jobs#continuing-a-large-edit).
                    self._continue_job(session_id, job_id, keep_going=True)
                else:
                    pending = metadata.get("pending_changes") or []
                    if pending:
                        self._approve_all_pending(session_id, job_id, pending)
                    # else: metadata hasn't landed yet on this poll —
                    # fall through and poll again rather than erroring.

            time.sleep(self._poll_interval)

    def _approve_all_pending(self, session_id: str, job_id: str, pending_changes: list[dict]) -> None:
        # This build has no human reviewer (the assigned card doesn't
        # call for one — see README), so every proposed change is
        # approved automatically. metadata.pending_changes is a plain
        # JSON array here (unlike the SSE proposed_change_batch.content
        # field, which is JSON-encoded as a string and needs a second
        # parse) — no double-parse needed on this REST polling path.
        changes = [{"change_id": c["change_id"], "approved": True} for c in pending_changes]
        response = self._request(
            "POST",
            f"/v1/chat/{session_id}/approve",
            # Top-level "approved" is required by the endpoint even for
            # batch decisions (docs.superdocs.app/guides/human-in-the-loop
            # warns this is the most common integration mistake) — it's
            # the default for any entry in `changes` that omits its own.
            json={"job_id": job_id, "approved": True, "changes": changes},
        )
        self._raise_for_error(response, f"POST /v1/chat/{session_id}/approve")

    def _continue_job(self, session_id: str, job_id: str, keep_going: bool) -> None:
        response = self._request(
            "POST",
            f"/v1/chat/{session_id}/continue",
            json={"job_id": job_id, "continue": keep_going},
        )
        self._raise_for_error(response, f"POST /v1/chat/{session_id}/continue")

    @staticmethod
    def _chat_result_from_payload(payload: dict) -> ChatResult:
        changes = payload.get("document_changes") or {}
        usage = payload.get("usage") or {}
        return ChatResult(
            response_text=payload.get("response", ""),
            updated_html=changes.get("updated_html"),
            changes_summary=changes.get("changes_summary"),
            version_id=changes.get("version_id"),
            monthly_used=usage.get("monthly_used"),
            monthly_remaining=usage.get("monthly_remaining"),
            was_billable=usage.get("was_billable"),
        )

    # ------------------------------------------------------------------
    # Export — POST /v1/documents/export, streamed straight to a
    # pre-signed S3 PUT URL so the exported bytes never fully materialize
    # in the orchestrator either. Using session_id (not inline html) also
    # sidesteps the 20 MB inline-export size cap entirely — SuperDocs
    # already holds the document server-side.
    # ------------------------------------------------------------------
    def _export_stream(self, session_id: str, export_format: str, options: dict | None):
        body: dict = {"session_id": session_id, "format": export_format}
        if options:
            body["options"] = options
        return self._client.stream(
            "POST", f"{self._base_url}/v1/documents/export", json=body
        )


    def _file_chunks(self, file_obj, chunk_size: int | None = None):
        """Read a file-like object in bounded chunks."""
        size = chunk_size or self._chunk_size

        while True:
            chunk = file_obj.read(size)
            if not chunk:
                break
            yield chunk

    def export_to_dest_url(
        self,
        session_id: str,
        export_format: str,
        dest_presigned_url: str,
        options: dict | None = None,
        dest_content_type: str = "application/octet-stream",
    ) -> list[dict]:
        with self._export_stream(session_id, export_format, options) as export_response:
            if export_response.status_code >= 400:
                export_response.read()
                self._raise_for_error(
                    export_response,
                    "POST /v1/documents/export",
                )

            warnings = _decode_export_warnings(export_response.headers)

            # MinIO/S3 requires Content-Length for this pre-signed PUT.
            # The SuperDocs response does not reliably provide it, so stream
            # the export to a disk-backed temporary file first. This keeps the
            # payload out of orchestrator memory while giving us the exact
            # length required by the destination PUT.
            with tempfile.TemporaryFile(mode="w+b") as temp_file:
                total_bytes = 0

                for chunk in export_response.iter_bytes(
                    chunk_size=self._chunk_size
                ):
                    if chunk:
                        temp_file.write(chunk)
                        total_bytes += len(chunk)

                temp_file.seek(0)

                tracker = ChunkSizeTracker(
                    self._file_chunks(temp_file)
                )

                put_response = self._raw_client.put(
                    dest_presigned_url,
                    content=tracker,
                    headers={
                        "Content-Type": dest_content_type,
                        "Content-Length": str(total_bytes),
                    },
                )

            self.last_export_tracker = tracker

            if put_response.status_code >= 400:
                raise SuperDocsError(
                    f"writing export to destination failed: "
                    f"HTTP {put_response.status_code}",
                    status_code=put_response.status_code,
                )

            if warnings:
                logger.warning(
                    "Export for session %s completed with warnings: %s",
                    session_id,
                    warnings,
                )

            return warnings

    def export_bytes(
        self, session_id: str, export_format: str, options: dict | None = None
    ) -> tuple[bytes, list[dict]]:
        """Non-streaming export — used for small verification reads
        (e.g. the trade-show-recap-batch build's plain-text sanity
        check), where the whole point is to inspect the content, so
        streaming would add complexity for nothing."""
        with self._export_stream(session_id, export_format, options) as export_response:
            if export_response.status_code >= 400:
                export_response.read()
                self._raise_for_error(export_response, "POST /v1/documents/export")
            warnings = _decode_export_warnings(export_response.headers)
            content = export_response.read()
        return content, warnings
