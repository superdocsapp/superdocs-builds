from __future__ import annotations

import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from soc2_index.logutil import JsonlLogger, redact_headers

Transport = Callable[[str, str, dict[str, str], Any], httpx.Response]

OPEN_MODES = {"replace", "new_focused", "background"}
SESSION_RE = __import__("re").compile(r"^[A-Za-z0-9_.-]{1,256}$")


class SuperDocsError(Exception):
    pass


class AuthError(SuperDocsError):
    pass


class RateLimited(SuperDocsError):
    def __init__(self, detail: str, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.retry_after = retry_after


class APIError(SuperDocsError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class TimeoutError_(SuperDocsError):
    pass


class JobFailed(SuperDocsError):
    def __init__(self, message: str, job_id: str) -> None:
        super().__init__(message)
        self.job_id = job_id


def _mime(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {
        ".md": "text/markdown",
        ".html": "text/html",
        ".htm": "text/html",
        ".txt": "text/plain",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(ext) or (mimetypes.guess_type(name)[0] or "application/octet-stream")


class Client:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.superdocs.app",
        transport: Transport | None = None,
        logger: JsonlLogger | None = None,
        user_agent: str = "soc2-evidence-index/0.1",
        timeout_connect: float = 30.0,
        timeout_io: float = 120.0,
        timeout_poll: float = 30.0,
        timeout_async: float = 30.0,
        poll_interval: float = 2.0,
        wait_timeout: float = 300.0,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("SUPERDOCS_API_KEY", "")
        if not key and transport is None:
            raise AuthError("SUPERDOCS_API_KEY is missing. Set SUPERDOCS_API_KEY=your-key-here")
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.logger = logger or JsonlLogger()
        self.user_agent = user_agent
        self.timeout_connect = timeout_connect
        self.timeout_io = timeout_io
        self.timeout_poll = timeout_poll
        self.timeout_async = timeout_async
        self.poll_interval = poll_interval
        self.wait_timeout = wait_timeout
        self._http: httpx.Client | None = None

    def _headers(self, extra: dict[str, str] | None = None, json_body: bool = False) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if json_body:
            h["Content-Type"] = "application/json"
        if extra:
            h.update(extra)
        return h

    def _http_client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=httpx.Timeout(self.timeout_io, connect=self.timeout_connect))
        return self._http

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        content: Any = None,
        files: Any = None,
        data: Any = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        url = path if path.startswith("http") else self.base_url + path
        hdrs = headers or self._headers(json_body=json_body is not None)
        body = json.dumps(json_body).encode("utf-8") if json_body is not None else content
        if self.transport is not None:
            resp = self.transport(method, url, hdrs, body if body is not None else data or files)
        elif files is not None:
            resp = self._http_client().request(
                method,
                url,
                headers=hdrs,
                files=files,
                data=data,
                timeout=timeout or self.timeout_io,
            )
        else:
            resp = self._http_client().request(
                method,
                url,
                headers=hdrs,
                content=body,
                timeout=timeout or self.timeout_io,
            )
        self.logger.log(
            "http",
            method=method,
            path=path.split("?")[0],
            status=resp.status_code,
            headers=redact_headers(dict(hdrs)),
        )
        return resp

    def _raise(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        detail = resp.text
        try:
            obj = resp.json()
            detail = obj.get("detail") or obj.get("error") or obj.get("message") or detail
            if not isinstance(detail, str):
                detail = json.dumps(detail)
        except Exception:
            pass
        if resp.status_code == 401:
            raise AuthError(detail or "unauthorized")
        if resp.status_code == 429:
            ra = resp.headers.get("retry-after")
            raise RateLimited(detail or "rate limited", int(ra) if ra and ra.isdigit() else None)
        if resp.status_code == 504:
            raise TimeoutError_(detail or "gateway/wall-clock timeout (30 min)")
        raise APIError(resp.status_code, detail or f"HTTP {resp.status_code}")

    def json(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.request(method, path, **kwargs)
        self._raise(resp)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {}

    def upload_template(self, path: Path) -> dict:
        with path.open("rb") as fh:
            files = {"file": (path.name, fh, _mime(path.name))}
            resp = self.request(
                "POST",
                "/v1/templates/upload",
                headers=self._headers(),
                files=files,
                timeout=self.timeout_io,
            )
        self._raise(resp)
        return resp.json() if resp.content else {}

    def list_templates(self) -> Any:
        return self.json("GET", "/v1/templates", headers=self._headers(), timeout=self.timeout_poll)

    def upload_document(self, path: Path, session_id: str, open_mode: str = "replace", filename: str | None = None) -> dict:
        if open_mode not in OPEN_MODES:
            raise ValueError(f"open_mode must be one of {sorted(OPEN_MODES)}")
        if not SESSION_RE.match(session_id):
            raise ValueError("invalid session_id")
        name = filename or path.name
        with path.open("rb") as fh:
            files = {"file": (name, fh, _mime(name))}
            data = {"session_id": session_id, "open_mode": open_mode}
            resp = self.request(
                "POST",
                "/v1/documents/upload",
                headers=self._headers(),
                files=files,
                data=data,
                timeout=self.timeout_io,
            )
        self._raise(resp)
        return resp.json()

    def list_documents(self, session_id: str, include_html: bool = False) -> dict:
        q = "?include_html=true" if include_html else ""
        return self.json(
            "GET",
            f"/v1/sessions/{session_id}/documents{q}",
            headers=self._headers(),
            timeout=self.timeout_poll,
        )

    def focus(self, session_id: str, document_id: str) -> dict:
        return self.json(
            "POST",
            f"/v1/sessions/{session_id}/documents/{document_id}/focus",
            headers=self._headers(json_body=True),
            json_body={},
            timeout=self.timeout_poll,
        )

    def close_document(self, session_id: str, document_id: str) -> dict:
        resp = self.request(
            "DELETE",
            f"/v1/sessions/{session_id}/documents/{document_id}",
            headers=self._headers(),
            timeout=self.timeout_poll,
        )
        self._raise(resp)
        return resp.json() if resp.content else {}

    def chat_async(
        self,
        message: str,
        session_id: str,
        *,
        document_id: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
    ) -> dict:
        if len(message) > 100_000:
            raise ValueError("message exceeds 100_000 characters")
        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "model_tier": model_tier,
        }
        if document_id:
            payload["document_id"] = document_id
        return self.json(
            "POST",
            "/v1/chat/async",
            headers=self._headers(json_body=True),
            json_body=payload,
            timeout=self.timeout_async,
        )

    def get_job(self, job_id: str, compact: bool = False) -> dict:
        q = "?compact=true" if compact else ""
        return self.json("GET", f"/v1/jobs/{job_id}{q}", headers=self._headers(), timeout=self.timeout_poll)

    def approve(self, session_id: str, body: dict) -> dict:
        self.json(
            "POST",
            f"/v1/chat/{session_id}/approve",
            headers=self._headers(json_body=True),
            json_body=body,
            timeout=self.timeout_poll,
        )
        return self.get_job(body["job_id"])

    def continue_job(self, session_id: str, job_id: str, resume: bool = True) -> dict:
        self.json(
            "POST",
            f"/v1/chat/{session_id}/continue",
            headers=self._headers(json_body=True),
            json_body={"job_id": job_id, "continue": resume},
            timeout=self.timeout_poll,
        )
        return self.get_job(job_id)

    def export(self, session_id: str, fmt: str, options: dict) -> tuple[bytes, dict[str, str]]:
        payload = {"session_id": session_id, "format": fmt, "options": options}
        resp = self.request(
            "POST",
            "/v1/documents/export",
            headers=self._headers(json_body=True, extra={"Accept": "*/*"}),
            json_body=payload,
            timeout=self.timeout_io,
        )
        self._raise(resp)
        return resp.content, {k.lower(): v for k, v in resp.headers.items()}

    def wait(self, job: dict, timeout: float | None = None) -> dict:
        t0 = time.time()
        last_info = t0
        current = job
        limit = timeout if timeout is not None else self.wait_timeout
        while True:
            elapsed = time.time() - t0
            if elapsed > limit:
                raise TimeoutError_(f"wait timed out after {limit}s")
            st = current.get("status")
            compact = st in ("pending", "in_progress")
            current = self.get_job(current["job_id"], compact=compact)
            if compact and current.get("status") in ("completed", "failed", "cancelled", "awaiting_approval"):
                current = self.get_job(current["job_id"], compact=False)
            if elapsed > 60 and (time.time() - last_info) >= 30:
                self.logger.log(
                    "still_processing",
                    job_id=current.get("job_id"),
                    status=current.get("status"),
                    elapsed_s=int(elapsed),
                )
                last_info = time.time()
            st = current.get("status")
            if st in ("completed", "failed", "cancelled", "awaiting_approval"):
                if st == "failed":
                    raise JobFailed(str(current.get("error") or "job failed"), current.get("job_id") or "")
                if st == "cancelled":
                    raise JobFailed("cancelled", current.get("job_id") or "")
                return current
            time.sleep(self.poll_interval)
