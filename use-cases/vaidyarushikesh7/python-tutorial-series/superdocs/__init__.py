"""A small SuperDocs client, standard library only.

Every tutorial part imports this. It exists so the tutorials can talk about the
API instead of about HTTP plumbing, and so the error handling in part three has
one place to live.

Nothing here needs pip. urllib is enough for JSON, for a pre-signed PUT and for
downloading a finished export.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app")

# The hosted gateway rejects request bodies larger than roughly 32 MB before the
# API ever sees them, and answers with HTML rather than JSON. Base64 inflates a
# file by about a third, so an inline upload stops being reliable well before the
# 50 MB the endpoint itself accepts. Part three uses this number to choose a path
# instead of finding out the hard way.
INLINE_UPLOAD_LIMIT_BYTES = 20 * 1024 * 1024


class SuperDocsError(RuntimeError):
    """Any failed call. Carries the status code and the body we could read."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class QuotaExhausted(SuperDocsError):
    """The account is out of operations for the month."""


class PayloadTooLarge(SuperDocsError):
    """The gateway refused the body before the API saw it."""


class JobFailed(SuperDocsError):
    """An async job reached status=failed."""


@dataclass
class Usage:
    """The usage block that rides along on every billable turn."""

    ops_charged: int = 0
    monthly_used: int = 0
    monthly_limit: int = 0
    monthly_remaining: int = 0
    quota_exhausted: bool = False

    @classmethod
    def from_response(cls, payload: dict | None) -> "Usage":
        u = payload or {}
        return cls(
            ops_charged=int(u.get("ops_charged") or 0),
            monthly_used=int(u.get("monthly_used") or 0),
            monthly_limit=int(u.get("monthly_limit") or 0),
            monthly_remaining=int(u.get("monthly_remaining") or 0),
            quota_exhausted=bool(u.get("quota_exhausted")),
        )


@dataclass
class Change:
    """One proposed edit, as it arrives while a job waits for approval."""

    change_id: str
    chunk_id: str = ""
    old_html: str = ""
    new_html: str = ""
    description: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict) -> "Change":
        return cls(
            change_id=str(
                payload.get("change_id")
                or payload.get("id")
                or payload.get("chunk_id")
                or ""
            ),
            chunk_id=str(payload.get("chunk_id") or ""),
            old_html=payload.get("old_html") or payload.get("before_html") or "",
            new_html=payload.get("new_html") or payload.get("after_html") or "",
            description=payload.get("description") or payload.get("summary") or "",
            raw=payload,
        )


class SuperDocs:
    """One instance per API key.

    Read timeouts default to five minutes because a deep edit on a long document
    genuinely works silently for a while. A quiet socket is not a dead one.
    """

    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL, timeout: int = 300):
        key = api_key or os.environ.get("SUPERDOCS_API_KEY", "")
        if not key:
            raise SuperDocsError(
                "No API key. Set SUPERDOCS_API_KEY, or pass api_key=. "
                "Create one at use.superdocs.app under settings."
            )
        self.api_key = key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ---------------------------------------------------------------- transport

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        timeout: int | None = None,
        retries: int = 2,
    ) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        attempt = 0
        while True:
            attempt += 1
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                return self._decode(raw, resp.status if hasattr(resp, "status") else 200, path)
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                # 413 from the gateway, and the HTML body that comes with it, is
                # the signature of a request that was too big to be looked at.
                if exc.code == 413 or (exc.code >= 400 and raw.lstrip().startswith("<")):
                    raise PayloadTooLarge(
                        f"{path} refused before the API saw it ({exc.code}). "
                        "The body was too large for the gateway. Use the pre-signed upload flow.",
                        exc.code,
                        raw[:400],
                    ) from exc
                if exc.code == 402 or "quota" in raw.lower():
                    detail = self._detail(raw)
                    if exc.code == 402 or "exhaust" in raw.lower():
                        raise QuotaExhausted(f"{path}: {detail}", exc.code, raw[:400]) from exc
                if exc.code in (429, 500, 502, 503, 504) and attempt <= retries:
                    time.sleep(2 ** attempt)
                    continue
                raise SuperDocsError(f"{path} -> {exc.code} {self._detail(raw)}", exc.code, raw[:800]) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt <= retries:
                    time.sleep(2 ** attempt)
                    continue
                raise SuperDocsError(f"{path} -> {exc}") from exc

    def request_raw(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        timeout: int | None = None,
    ) -> tuple[bytes, dict]:
        """Same as request, for endpoints that answer with a file rather than JSON.

        /v1/documents/export is one of them: it returns the .docx or .pdf bytes
        with a content-disposition header, even though the published OpenAPI
        schema describes a JSON body. Asking for JSON there gets you a zip.
        """
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.read(), dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if exc.code == 413 or (exc.code >= 400 and raw.lstrip().startswith("<")):
                raise PayloadTooLarge(f"{path} refused before the API saw it ({exc.code}).", exc.code, raw[:400]) from exc
            raise SuperDocsError(f"{path} -> {exc.code} {self._detail(raw)}", exc.code, raw[:800]) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SuperDocsError(f"{path} -> {exc}") from exc

    @staticmethod
    def _decode(raw: str, status: int, path: str) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SuperDocsError(
                f"{path} answered {status} with something that is not JSON: {raw[:200]!r}",
                status,
                raw[:400],
            ) from exc

    @staticmethod
    def _detail(raw: str) -> str:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw[:300]
        if isinstance(parsed, dict):
            return str(parsed.get("detail") or parsed.get("message") or parsed)[:300]
        return str(parsed)[:300]

    # ------------------------------------------------------------------ account

    def whoami(self) -> dict:
        """Tier, operations used, operations left. Not billable. Call it first."""
        return self.request("GET", "/v1/agents/whoami")

    # ----------------------------------------------------------------- sessions

    def init_session(self, document_ids: list[str] | None = None) -> str:
        out = self.request("POST", "/v1/sessions/init", {"document_ids": document_ids})
        session_id = out.get("session_id") or out.get("id") or (out.get("session") or {}).get("id")
        if not session_id:
            raise SuperDocsError(f"no session id in {json.dumps(out)[:200]}")
        return session_id

    # --------------------------------------------------------------------- chat

    def chat(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        response_mode: str = "full",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
    ) -> dict:
        """One synchronous turn. Billable when it changes the document.

        Pass document_html on the first turn only. The session holds the document
        after that, and re-sending it every turn wastes tokens for no gain.
        """
        payload: dict = {
            "session_id": session_id,
            "message": message,
            "response_mode": response_mode,
        }
        if document_html is not None:
            payload["document_html"] = document_html
        if model_tier:
            payload["model_tier"] = model_tier
        if thinking_depth:
            payload["thinking_depth"] = thinking_depth
        out = self.request("POST", "/v1/chat", payload)
        usage = Usage.from_response(out.get("usage"))
        if usage.quota_exhausted:
            raise QuotaExhausted("monthly operations are gone; the edit did not apply")
        return out

    def chat_async(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str | None = None,
        response_mode: str = "full",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
    ) -> str:
        """Start a job and get a job_id back. Poll it with get_job."""
        payload: dict = {
            "session_id": session_id,
            "message": message,
            "response_mode": response_mode,
            "async_mode": True,
        }
        if document_html is not None:
            payload["document_html"] = document_html
        if approval_mode:
            payload["approval_mode"] = approval_mode
        if model_tier:
            payload["model_tier"] = model_tier
        if thinking_depth:
            payload["thinking_depth"] = thinking_depth
        out = self.request("POST", "/v1/chat/async", payload)
        job_id = out.get("job_id")
        if not job_id:
            raise SuperDocsError(f"no job_id in {json.dumps(out)[:200]}")
        return job_id

    # --------------------------------------------------------------------- jobs

    def get_job(self, job_id: str) -> dict:
        return self.request("GET", f"/v1/jobs/{job_id}")

    def wait_for_job(
        self,
        job_id: str,
        stop_on: tuple[str, ...] = ("completed", "failed", "cancelled", "awaiting_approval"),
        interval: float = 3.0,
        max_wait: float = 900.0,
        on_progress=None,
    ) -> dict:
        """Poll until the job reaches one of stop_on, then hand back the job.

        A quiet job is a working job. The only real failure here is running out
        of patience, so max_wait is generous and explicit rather than hidden.
        """
        started = time.time()
        last = None
        while True:
            job = self.get_job(job_id)
            status = job.get("status")
            if on_progress and (status, job.get("progress")) != last:
                on_progress(job)
                last = (status, job.get("progress"))
            if status in stop_on:
                if status == "failed":
                    raise JobFailed(job.get("error") or "job failed with no error text")
                return job
            if time.time() - started > max_wait:
                raise SuperDocsError(
                    f"job {job_id} still {status} after {int(max_wait)}s. "
                    "It keeps running server side; poll it again rather than starting another."
                )
            time.sleep(interval)

    def pending_changes(self, job: dict) -> list[Change]:
        meta = job.get("metadata") or {}
        return [Change.from_payload(c) for c in (meta.get("pending_changes") or [])]

    def approve(
        self,
        session_id: str,
        job_id: str,
        approved: bool,
        change_id: str | None = None,
        feedback: str | None = None,
        changes: list[dict] | None = None,
    ) -> dict:
        payload: dict = {"job_id": job_id, "approved": approved}
        if change_id:
            payload["change_id"] = change_id
        if feedback:
            payload["feedback"] = feedback
        if changes:
            payload["changes"] = changes
        return self.request("POST", f"/v1/chat/{session_id}/approve", payload)

    def continue_job(self, session_id: str, job_id: str, keep_going: bool) -> dict:
        """Answer a large-edit pause. Not the same thing as approving a change."""
        return self.request(
            "POST",
            f"/v1/chat/{session_id}/continue",
            {"job_id": job_id, "continue": keep_going},
        )

    # ------------------------------------------------------------------- uploads

    def upload_base64(
        self,
        filename: str,
        file_bytes: bytes,
        session_id: str | None = None,
        return_html: bool = False,
    ) -> dict:
        """Inline upload. Fine for small files, wrong for large ones.

        The guard is deliberate: without it a 30 MB docx becomes a 40 MB request
        body and comes back as an HTML error page from the gateway, which is a
        confusing way to learn about a limit.
        """
        import base64

        if len(file_bytes) > INLINE_UPLOAD_LIMIT_BYTES:
            raise PayloadTooLarge(
                f"{filename} is {len(file_bytes) / 1e6:.1f} MB. Base64 would push the request "
                f"past the ~32 MB gateway cap. Use upload_via_url instead."
            )
        payload = {
            "filename": filename,
            "file_base64": base64.b64encode(file_bytes).decode(),
            "return_html": return_html,
        }
        if session_id:
            payload["session_id"] = session_id
        return self.request("POST", "/v1/documents/upload-base64", payload)

    def request_upload_url(self, filename: str, content_type: str, size_bytes: int) -> dict:
        return self.request(
            "POST",
            "/v1/uploads",
            {"filename": filename, "content_type": content_type, "size_bytes": size_bytes},
        )

    @staticmethod
    def put_bytes(upload_url: str, file_bytes: bytes, content_type: str, timeout: int = 600) -> int:
        """PUT the file straight at storage. The API never sees these bytes."""
        req = urllib.request.Request(
            upload_url,
            data=file_bytes,
            method="PUT",
            headers={"Content-Type": content_type},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            hint = ""
            if exc.code in (400, 403):
                hint = (
                    " The pre-signed URL lasts five minutes and is bound to the "
                    "content type and size you declared. Ask for a fresh one."
                )
            raise SuperDocsError(f"PUT failed: {exc.code}.{hint} {raw[:300]}", exc.code, raw[:300]) from exc

    def process_upload(
        self,
        upload_id: str,
        session_id: str,
        filename: str,
        parse_mode: str = "document",
        return_html: bool = False,
    ) -> dict:
        """Parse an uploaded file into chunked HTML. Parsing is not billable."""
        return self.request(
            "POST",
            f"/v1/uploads/{upload_id}/process",
            {
                "session_id": session_id,
                "filename": filename,
                "parse_mode": parse_mode,
                "return_html": return_html,
            },
            timeout=600,
        )

    def upload_document(
        self,
        session_id: str,
        path,
        content_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        return_html: bool = False,
    ) -> dict:
        """Pick the right upload path by file size, and say which one was used."""
        from pathlib import Path

        p = Path(path)
        data = p.read_bytes()
        if len(data) <= INLINE_UPLOAD_LIMIT_BYTES:
            out = self.upload_base64(p.name, data, session_id=session_id, return_html=return_html)
            out["_path_used"] = "inline"
            return out
        return self.upload_via_url(session_id, p, content_type=content_type, return_html=return_html)

    def upload_via_url(
        self,
        session_id: str,
        path,
        content_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        return_html: bool = False,
    ) -> dict:
        from pathlib import Path

        p = Path(path)
        data = p.read_bytes()
        ticket = self.request_upload_url(p.name, content_type, len(data))
        self.put_bytes(ticket["upload_url"], data, content_type)
        out = self.process_upload(ticket["upload_id"], session_id, p.name, return_html=return_html)
        out["_path_used"] = "presigned"
        out["_upload_id"] = ticket["upload_id"]
        return out

    # ------------------------------------------------------------------- exports

    def export(
        self,
        session_id: str | None = None,
        html: str | None = None,
        fmt: str = "docx",
        filename: str | None = None,
        options: dict | None = None,
    ) -> dict:
        """Export a session's current state, or ad-hoc HTML. Not billable.

        Returns {"bytes": b"...", "filename": ..., "content_type": ...}. The
        endpoint hands back the file itself, so this method does too, and
        save_export writes whichever shape it gets.
        """
        payload: dict = {"format": fmt}
        if session_id:
            payload["session_id"] = session_id
        if html is not None:
            payload["html"] = html
        if filename:
            payload["filename"] = filename
        if options:
            payload["options"] = options
        raw, headers = self.request_raw("POST", "/v1/documents/export", payload, timeout=600)
        # HTTP/2 sends header names lowercase, so never look them up case-sensitively.
        lower = {k.lower(): v for k, v in headers.items()}
        content_type = lower.get("content-type", "")
        if content_type.startswith("application/json"):
            return self._decode(raw.decode("utf-8", errors="replace"), 200, "/v1/documents/export")
        name = filename or ""
        disposition = lower.get("content-disposition", "")
        if not name and "filename=" in disposition:
            name = disposition.split('filename="')[-1].split('"')[0]
        return {"bytes": raw, "filename": name or f"document.{fmt}", "content_type": content_type}

    def download_url(
        self,
        session_id: str,
        fmt: str = "docx",
        filename: str | None = None,
        options: dict | None = None,
    ) -> dict:
        """A signed GET URL that lasts fifteen minutes."""
        payload: dict = {"session_id": session_id, "format": fmt}
        if filename:
            payload["filename"] = filename
        if options:
            payload["options"] = options
        return self.request("POST", "/v1/downloads", payload, timeout=600)

    def request_export_by_email(
        self,
        session_id: str,
        fmt: str = "docx",
        filename: str | None = None,
        recipient_email: str | None = None,
    ) -> dict:
        """The fallback when a document is too big to export while you wait."""
        payload: dict = {"session_id": session_id, "format": fmt}
        if filename:
            payload["filename"] = filename
        if recipient_email:
            payload["recipient_email"] = recipient_email
        return self.request("POST", "/v1/documents/export/email-request", payload)

    @staticmethod
    def save_from_url(url: str, dest, timeout: int = 600) -> int:
        """Stream a signed URL to disk without holding the file in memory."""
        from pathlib import Path

        target = Path(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp, target.open("wb") as fh:
            written = 0
            while True:
                block = resp.read(1024 * 256)
                if not block:
                    break
                fh.write(block)
                written += len(block)
        return written


def save_export(payload: dict, dest) -> int:
    """Write whatever an export response carried back to disk.

    The response is either a signed URL, base64 bytes, or text, depending on the
    format asked for. Handling all three here keeps the tutorials short.
    """
    import base64
    from pathlib import Path

    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(payload.get("bytes"), bytes):
        target.write_bytes(payload["bytes"])
        return len(payload["bytes"])

    for key in ("download_url", "url", "signed_url"):
        if payload.get(key):
            return SuperDocs.save_from_url(payload[key], target)

    for key in ("file_base64", "content_base64", "data_base64", "base64"):
        if payload.get(key):
            raw = base64.b64decode(payload[key])
            target.write_bytes(raw)
            return len(raw)

    for key in ("html", "content", "text", "markdown"):
        if payload.get(key):
            text = payload[key]
            target.write_text(text, encoding="utf-8")
            return len(text.encode())

    raise SuperDocsError(f"nothing downloadable in export response: {sorted(payload)[:12]}")
