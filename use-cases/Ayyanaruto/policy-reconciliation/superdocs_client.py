"""Thin SuperDocs REST wrapper. One retry, no frameworks."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app").rstrip("/")
MIN_REMAINING = int(os.environ.get("SUPERDOCS_MIN_REMAINING", "20"))
POLL_INTERVAL = 2
MAX_POLL_SECONDS = 900


class SuperDocsError(Exception):
    pass


class QuotaExhausted(SuperDocsError):
    pass


def load_dotenv(path=None):
    """Load KEY=VALUE lines into os.environ (does not override existing vars)."""
    candidates = []
    if path:
        candidates.append(Path(path))
    here = Path(__file__).resolve().parent
    candidates.extend(
        [
            here / ".env",
            here.parent / ".env",
            Path.cwd() / ".env",
        ]
    )
    seen = set()
    for env_path in candidates:
        env_path = env_path.resolve()
        if env_path in seen or not env_path.is_file():
            continue
        seen.add(env_path)
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)
    global BASE_URL, MIN_REMAINING
    BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", BASE_URL).rstrip("/")
    MIN_REMAINING = int(os.environ.get("SUPERDOCS_MIN_REMAINING", str(MIN_REMAINING)))


def _api_key():
    key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    if not key:
        raise SuperDocsError(
            "SUPERDOCS_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return key


def _headers(json_content=True):
    headers = {"Authorization": f"Bearer {_api_key()}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def _request(method, path, *, json_body=None, files=None, data=None, params=None, retry=True):
    url = f"{BASE_URL}{path}"
    kwargs = {"timeout": 90}
    if files is not None:
        kwargs["headers"] = _headers(json_content=False)
        kwargs["files"] = files
        if data is not None:
            kwargs["data"] = data
    else:
        kwargs["headers"] = _headers(json_content=True)
        if json_body is not None:
            kwargs["json"] = json_body
    if params:
        kwargs["params"] = params

    try:
        resp = requests.request(method, url, **kwargs)
    except (requests.ConnectionError, requests.Timeout) as exc:
        # Don't retry multipart: the file handle is already consumed.
        if retry and files is None:
            time.sleep(2)
            return _request(
                method,
                path,
                json_body=json_body,
                files=files,
                data=data,
                params=params,
                retry=False,
            )
        raise SuperDocsError(f"Request failed: {exc}") from exc

    if resp.status_code >= 500 and retry and files is None:
        time.sleep(2)
        return _request(
            method,
            path,
            json_body=json_body,
            files=files,
            data=data,
            params=params,
            retry=False,
        )

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        remaining = resp.headers.get("X-Usage-Remaining")
        used = resp.headers.get("X-Usage-Used")
        limit = resp.headers.get("X-Usage-Limit")
        msg = (
            f"Rate limited (429). X-Usage-Remaining={remaining} "
            f"X-Usage-Used={used} X-Usage-Limit={limit}"
        )
        if retry_after:
            msg += f" Retry-After={retry_after}s"
        raise SuperDocsError(msg)

    if not resp.ok:
        raise SuperDocsError(f"{method} {path} -> {resp.status_code}: {resp.text[:800]}")
    return resp


def check_usage(usage):
    if not usage:
        return
    remaining = usage.get("monthly_remaining")
    if remaining is not None and int(remaining) < MIN_REMAINING:
        raise QuotaExhausted(
            f"Stopping: only {remaining} SuperDocs operations remaining "
            f"(threshold {MIN_REMAINING}). Upgrade or wait for the monthly reset."
        )


def verify_key():
    _request("GET", "/v1/sessions")
    return True


def account_status():
    resp = _request("GET", "/v1/agents/whoami")
    return resp.json()


def check_quota_or_stop():
    try:
        status = account_status()
    except SuperDocsError:
        return None
    quota = status.get("quota") or {}
    remaining = quota.get("remaining")
    if remaining is not None and int(remaining) < MIN_REMAINING:
        raise QuotaExhausted(
            f"Stopping: only {remaining} SuperDocs operations remaining "
            f"(threshold {MIN_REMAINING}). Upgrade or wait for the monthly reset."
        )
    return status


def document_id_from_payload(payload):
    """Session-local `document_id` from an upload/roster payload. Ignore top-level `id`."""
    if not isinstance(payload, dict):
        return None
    value = payload.get("document_id")
    if value and not isinstance(value, (dict, list)):
        return value
    for nested_key in ("document", "focused_document"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            found = document_id_from_payload(nested)
            if found:
                return found
    roster = payload.get("documents") or payload.get("open_documents") or []
    if isinstance(roster, dict):
        roster = roster.get("items") or roster.get("documents") or []
    if isinstance(roster, list) and roster:
        focused = next((item for item in roster if isinstance(item, dict) and item.get("focused")), None)
        target = focused or roster[-1]
        if isinstance(target, dict):
            return document_id_from_payload(target)
    return None


def list_session_documents(session_id, include_html=False):
    params = {"include_html": "true"} if include_html else None
    resp = _request("GET", f"/v1/sessions/{session_id}/documents", params=params)
    payload = resp.json()
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        docs = payload.get("documents") or payload.get("items") or payload.get("open_documents")
        if isinstance(docs, list):
            return docs
    return []


def upload(path, session_id, open_mode="replace"):
    path = Path(path)
    last_error = None
    resp = None
    for attempt in range(2):
        try:
            with path.open("rb") as handle:
                resp = _request(
                    "POST",
                    "/v1/documents/upload",
                    files={
                        "file": (
                            path.name,
                            handle,
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        )
                    },
                    data={"session_id": session_id, "open_mode": open_mode},
                    params={"index": "true"},
                    retry=False,
                )
            break
        except SuperDocsError as exc:
            last_error = exc
            retryable = "Request failed" in str(exc) or "-> 5" in str(exc)
            if attempt == 0 and retryable:
                time.sleep(2)
                continue
            raise
    if resp is None:
        raise last_error
    payload = resp.json()
    document_id = document_id_from_payload(payload)
    if not document_id:
        roster = list_session_documents(session_id)
        focused = next((d for d in roster if isinstance(d, dict) and d.get("focused")), None)
        document_id = document_id_from_payload(focused or (roster[-1] if roster else {}) or {})
    return {
        "filename": path.name,
        "path": str(path.resolve()),
        "session_id": session_id,
        "document_id": document_id,
        "chunks_count": payload.get("chunks_count"),
        "html": payload.get("html"),
        "raw": payload,
    }


def new_blank_document(session_id):
    resp = _request("POST", f"/v1/sessions/{session_id}/documents/blank")
    payload = resp.json() if resp.content else {}
    document_id = document_id_from_payload(payload)
    if not document_id:
        roster = list_session_documents(session_id)
        focused = next((d for d in roster if isinstance(d, dict) and d.get("focused")), None)
        document_id = document_id_from_payload(focused or (roster[-1] if roster else {}) or {})
    return {"session_id": session_id, "document_id": document_id, "raw": payload}


def get_job(job_id):
    resp = _request("GET", f"/v1/jobs/{job_id}")
    return resp.json()


def continue_chat(session_id, job_id, keep_going=True):
    resp = _request(
        "POST",
        f"/v1/chat/{session_id}/continue",
        json_body={"job_id": job_id, "continue": bool(keep_going)},
    )
    return resp.json() if resp.content else {}


def poll_job(job_id, session_id=None, *, allow_approval=True):
    started = time.time()
    last_warn = 0
    while True:
        job = get_job(job_id)
        status = job.get("status")
        elapsed = time.time() - started
        if status == "completed":
            result = job.get("result") or {}
            check_usage(result.get("usage") or job.get("usage"))
            return job
        if status == "failed":
            raise SuperDocsError(f"Job {job_id} failed: {job.get('error')}")
        if status == "cancelled":
            raise SuperDocsError(f"Job {job_id} was cancelled")
        if status == "awaiting_approval":
            meta = job.get("metadata") or {}
            if meta.get("awaiting_kind") == "continue_prompt":
                sid = session_id or job.get("session_id")
                if not sid:
                    raise SuperDocsError(
                        f"Job {job_id} paused for continue_prompt but no session_id is available"
                    )
                print(f"  continue_prompt: resuming job {job_id}")
                continue_chat(sid, job_id, True)
            elif allow_approval:
                return job
        if elapsed > MAX_POLL_SECONDS:
            raise SuperDocsError(f"Job {job_id} did not finish within {MAX_POLL_SECONDS}s")
        if elapsed > 60 and elapsed - last_warn >= 30:
            print(f"  still processing job {job_id} ({int(elapsed)}s)")
            last_warn = elapsed
        time.sleep(POLL_INTERVAL)


def chat_async(
    message,
    session_id,
    *,
    document_id=None,
    model_tier="core",
    thinking_depth=None,
    approval_mode=None,
    wait=True,
    allow_approval=True,
):
    body = {
        "message": message,
        "session_id": session_id,
        "model_tier": model_tier,
    }
    if thinking_depth:
        body["thinking_depth"] = thinking_depth
    if document_id:
        body["document_id"] = document_id
    if approval_mode:
        body["approval_mode"] = approval_mode
    resp = _request("POST", "/v1/chat/async", json_body=body)
    started = resp.json()
    job_id = started.get("job_id")
    if not job_id:
        raise SuperDocsError(f"chat_async returned no job_id: {started}")
    if not wait:
        return {"job_id": job_id, "status": started.get("status"), "raw": started}
    job = poll_job(job_id, session_id=session_id, allow_approval=allow_approval)
    return job


def approve(session_id, job_id, approved, change_id=None, changes=None, feedback=None):
    body = {"job_id": job_id, "approved": bool(approved)}
    if change_id:
        body["change_id"] = change_id
    if changes:
        body["changes"] = changes
    if feedback:
        body["feedback"] = feedback
    resp = _request("POST", f"/v1/chat/{session_id}/approve", json_body=body)
    return resp.json() if resp.content else {}


def export_docx(dest, *, session_id=None, html=None, filename=None):
    body = {"format": "docx"}
    if session_id:
        body["session_id"] = session_id
    if html:
        body["html"] = html
    if filename:
        body["options"] = {"filename": filename}
    if not session_id and not html:
        raise SuperDocsError("export_docx requires session_id or html")
    resp = _request("POST", "/v1/documents/export", json_body=body)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def parse_pending_changes(raw):
    """Defensive parse: pending_changes may arrive as a JSON string (documented gotcha)."""
    if raw is None:
        return []
    data = raw
    for _ in range(3):
        if isinstance(data, str):
            data = data.strip()
            if not data:
                return []
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return []
            continue
        break
    if isinstance(data, dict):
        data = data.get("pending_changes") or data.get("changes") or [data]
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                continue
        if isinstance(item, dict):
            out.append(item)
    return out


def parse_json_from_reply(text):
    """Pull a JSON object/array out of a model reply, including fenced blocks.

    Returns None for empty or non-JSON replies instead of raising.
    """
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text
    s = str(text).strip()
    if not s:
        return None
    if s.startswith("```"):
        lines = s.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        if lines and lines[0].strip().lower() in {"json", "javascript", "js"}:
            lines = lines[1:]
        s = "\n".join(lines).strip()
    start_obj, start_arr = s.find("{"), s.find("[")
    starts = [i for i in (start_obj, start_arr) if i >= 0]
    if starts:
        s = s[min(starts) :]
        end = max(s.rfind("}"), s.rfind("]"))
        if end >= 0:
            s = s[: end + 1]
    if not s:
        return None
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    return data


SAFETY_REFUSAL_MARKERS = (
    "wasn't able to put together a safe reply",
    "was not able to put together a safe reply",
    "safe reply to share here",
    "could you rephrase",
)


def is_safety_refusal(text):
    """True when SuperDocs declined to answer (content filter), not when it returned JSON."""
    s = str(text or "").lower()
    return any(marker in s for marker in SAFETY_REFUSAL_MARKERS)


def reply_text(job):
    """Best-effort AI reply text from a chat job (field names vary)."""
    if not job:
        return ""
    result = job.get("result") or {}
    if isinstance(result, str):
        return result
    candidates = []
    if isinstance(result, dict):
        candidates.extend([result.get("response"), result.get("message"), result.get("text")])
    candidates.extend([job.get("response"), job.get("message")])
    meta = job.get("metadata") or {}
    intermediates = []
    if isinstance(result, dict):
        intermediates = result.get("intermediate_responses") or []
    if not intermediates:
        intermediates = meta.get("intermediate_responses") or []
    if isinstance(intermediates, list):
        for item in reversed(intermediates):
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                candidates.append(item.get("content") or item.get("text") or item.get("response"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
        if isinstance(candidate, (dict, list)):
            return candidate
    return ""
