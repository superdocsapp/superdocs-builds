import json as _json
import re
import time
from pathlib import Path

import requests

from . import config


class OpsFloorExceeded(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


class MaxWaitExceeded(RuntimeError):
    pass


class HttpTransport:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._key = api_key if api_key is not None else config.api_key()
        self._base = (base_url or config.base_url()).rstrip("/")
        self.last_headers: dict = {}

    def request(self, method: str, path: str, *, params=None, json_body=None,
                data=None, files=None):
        headers = {"Authorization": f"Bearer {self._key}"}
        url = self._base + path
        resp = requests.request(
            method, url, params=params, json=json_body, data=data,
            files=files, headers=headers, timeout=60,
        )
        self.last_headers = dict(resp.headers)
        if resp.status_code >= 400:
            raise ApiError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"_binary": True, "_content": resp.content,
                    "_headers": dict(resp.headers)}


class FixtureTransport:
    def __init__(self, script_path: str | Path | list):
        script = script_path if isinstance(script_path, list) else \
            _json.loads(Path(script_path).read_text())
        self.steps = script
        self.calls: list[tuple[str, str]] = []
        self.bodies: list[dict | None] = []
        self.last_headers: dict = {}

    def request(self, method: str, path: str, *, params=None, json_body=None,
                data=None, files=None):
        self.calls.append((method, path))
        self.bodies.append(json_body)
        want = params or {}
        for step in self.steps:
            if step["method"] != method:
                continue
            pattern = step["path"].replace("{id}", "[^/]+")
            if not re.fullmatch(pattern, path):
                continue
            step_params = step.get("params") or {}
            if set(step_params.keys()) != set(want.keys()):
                continue
            if any(str(want[k]) != v for k, v in step_params.items()):
                continue
            responses = step["responses"]
            head = responses[0]
            if len(responses) > 1:
                step["responses"] = responses[1:]
            headers = dict(step.get("headers") or {})
            if isinstance(head, dict) and head.get("headers"):
                merged = dict(head)
                headers.update(merged.pop("headers") or {})
                head = merged
            self.last_headers = headers
            return head
        raise LookupError(f"no fixture step for {method} {path}")


class SuperDocsClient:
    BILLABLE_CALLS = {"chat", "chat_async"}

    def __init__(self, transport, usage_log=None, poll_interval=None):
        self.t = transport
        self.usage_log = usage_log if usage_log is not None else []
        self.poll_interval = poll_interval if poll_interval is not None \
            else config.POLL_INTERVAL_S

    def _capture_usage(self, call: str, payload: dict, job_id: str | None = None):
        usage = payload.get("usage")
        if not usage:
            return
        entry = {
            "ts": _now(), "call": call,
            "job_id": job_id or payload.get("job_id"),
            "ops_charged": int(usage.get("ops_charged", 0)),
            "was_billable": bool(usage.get("was_billable")),
            "monthly_used": usage.get("monthly_used"),
            "monthly_remaining": usage.get("monthly_remaining"),
            "quota_exhausted": bool(usage.get("quota_exhausted")),
            "note": None,
        }
        self.usage_log.append(entry)
        remaining = usage.get("monthly_remaining")
        if remaining is not None and remaining < config.OPS_SAFETY_FLOOR:
            raise OpsFloorExceeded(
                f"aborting: monthly_remaining={remaining} below safety floor "
                f"{config.OPS_SAFETY_FLOOR}"
            )

    def key_sanity(self) -> dict:
        return self.t.request("GET", "/v1/sessions")

    def create_session(self, session_id: str | None = None,
                       document_ids: list[str] | None = None) -> dict:
        body = {}
        if session_id:
            body["session_id"] = session_id
        if document_ids:
            body["document_ids"] = document_ids
        return self.t.request("POST", "/v1/sessions/init",
                              json_body=body)

    def upload_document(self, session_id: str, filepath: str,
                        open_mode: str | None = None) -> dict:
        name = Path(filepath).name
        with open(filepath, "rb") as fh:
            files = {"file": (name, fh)}
            data = {"session_id": session_id}
            if open_mode:
                data["open_mode"] = open_mode
            return self.t.request("POST", "/v1/documents/upload",
                                  data=data, files=files)

    def save_document(self, session_id: str, document_id: str,
                      html: str, base_html: str) -> dict:
        return self.t.request(
            "POST", f"/v1/sessions/{session_id}/documents/{document_id}/save",
            json_body={"html": html, "base_html": base_html},
        )

    def roster(self, session_id: str, include_html: bool = False,
               report_changed: bool = False) -> list[dict]:
        params = {}
        if include_html:
            params["include_html"] = "true"
        if report_changed:
            params["report_changed"] = "true"
        out = self.t.request(
            "GET", f"/v1/sessions/{session_id}/documents", params=params)
        return out.get("documents", out) if isinstance(out, dict) else out

    def doc_events(self, session_id: str, after_id: int = 0) -> dict:
        out = self.t.request(
            "GET", f"/v1/sessions/{session_id}/doc-events",
            params={"after_id": str(after_id)})
        return out

    def document(self, session_id: str, document_id: str) -> dict:
        return self.t.request(
            "GET", f"/v1/documents/{document_id}")

    def document_detail(self, durable_document_id: str) -> dict:
        return self.t.request("GET",
                              f"/v1/documents/{durable_document_id}")

    def upload_template(self, filepath: str) -> dict:
        name = Path(filepath).name
        with open(filepath, "rb") as fh:
            return self.t.request("POST", "/v1/templates/upload",
                                  files={"file": (name, fh)})

    def list_templates(self) -> dict:
        return self.t.request("GET", "/v1/templates")

    def focus_document(self, session_id: str, document_id: str) -> dict:
        return self.t.request(
            "POST",
            f"/v1/sessions/{session_id}/documents/{document_id}/focus")

    def request_download(self, session_id: str, fmt: str,
                         filename: str | None = None) -> dict:
        body: dict = {"session_id": session_id, "format": fmt}
        if filename:
            body["filename"] = filename
        return self.t.request("POST", "/v1/downloads", json_body=body)

    def last_response_headers(self) -> dict:
        return dict(getattr(self.t, "last_headers", {}) or {})

    def export_warnings(self) -> list[str]:
        import base64
        raw = self.last_response_headers().get("X-Export-Warnings")
        if not raw:
            return []
        try:
            decoded = _json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception:
            return [str(raw)]
        if isinstance(decoded, list):
            return [str(item) for item in decoded]
        return [str(decoded)]

    def fetch_to_file(self, url: str, path: str) -> int:
        if isinstance(self.t, FixtureTransport):
            payload = f"fixture-download:{url[:120]}".encode()
            Path(path).write_bytes(payload)
            return len(payload)
        size = 0
        with requests.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        fh.write(chunk)
                        size += len(chunk)
        return size

    def chat(self, message: str, session_id: str, document_id: str | None = None,
             approval_mode: str | None = None) -> dict:
        body = {"message": message, "session_id": session_id,
                "response_mode": "compact"}
        if document_id:
            body["document_id"] = document_id
        if approval_mode:
            body["approval_mode"] = approval_mode
        resp = self.t.request("POST", "/v1/chat", json_body=body)
        self._capture_usage("chat", resp)
        return resp

    def chat_async(self, message: str, session_id: str,
                   document_id: str | None = None,
                   approval_mode: str | None = None) -> dict:
        body = {"message": message, "session_id": session_id,
                "response_mode": "compact"}
        if document_id:
            body["document_id"] = document_id
        if approval_mode:
            body["approval_mode"] = approval_mode
        return self.t.request("POST", "/v1/chat/async", json_body=body)

    def chat_wait(self, message: str, session_id: str,
                  document_id: str | None = None,
                  latency_class: str = "verification_turn") -> dict:
        try:
            start = self.chat_async(message, session_id,
                                    document_id=document_id)
        except ApiError as exc:
            if "session_busy" not in str(exc):
                raise
            blocking = _blocking_job_id(str(exc))
            print(f"[session busy] waiting for blocking job {blocking}...")
            if blocking:
                done = self.poll_job(blocking, latency_class)
                if done.get("status") == "completed":
                    self._capture_usage("chat_async", done.get("result") or {},
                                        blocking)
            start = self.chat_async(message, session_id,
                                    document_id=document_id)
        job_id = start["job_id"]
        job = self.poll_job(job_id, latency_class)
        if job.get("status") != "completed":
            raise RuntimeError(f"chat job {job_id} ended "
                               f"{job.get('status')}")
        result = job.get("result") or {}
        self._capture_usage("chat_async", result, job_id)
        return {"response": result.get("response", ""),
                "usage": result.get("usage"), "job_id": job_id}

    def register_our_job(self, conn, job_id: str, purpose: str):
        conn.execute(
            "INSERT OR IGNORE INTO our_jobs(job_id, purpose, created_at) "
            "VALUES(?, ?, ?)", (job_id, purpose, _now()))
        conn.commit()

    def job(self, job_id: str) -> dict:
        return self.t.request("GET", f"/v1/jobs/{job_id}")

    def pending_jobs(self, session_id: str) -> list[dict]:
        out = self.t.request("GET", f"/v1/sessions/{session_id}/jobs")
        jobs = out.get("jobs", []) if isinstance(out, dict) else []
        return [j for j in jobs if j.get("status") == "awaiting_approval"]

    def continue_chat(self, session_id: str, job_id: str,
                      cont: bool = True) -> dict:
        return self.t.request(
            "POST", f"/v1/chat/{session_id}/continue",
            json_body={"job_id": job_id, "continue": cont})

    def approve(self, session_id: str, job_id: str, changes: list[dict],
                default_approved: bool) -> dict:
        payload = {"job_id": job_id, "approved": default_approved,
                   "changes": changes}
        resp = self.t.request(
            "POST", f"/v1/chat/{session_id}/approve", json_body=payload)
        self._capture_usage("approve", resp, job_id)
        return resp

    def capture_job_result(self, job: dict):
        result = job.get("result") or {}
        self._capture_usage("job_completed", result,
                            job.get("job_id"))

    def poll_job(self, job_id: str, latency_class: str = "complex_edit",
                 pause_on: set | None = None):
        terminal = {"completed", "failed", "cancelled"} | (pause_on or set())
        limits = config.LATENCY.get(latency_class, config.LATENCY["complex_edit"])
        started = time.monotonic()
        warned = False
        while True:
            job = self.job(job_id)
            status = job.get("status")
            if status in terminal:
                return job
            elapsed = time.monotonic() - started
            if not warned and elapsed > limits["warn_after"]:
                print(f"[still processing] job {job_id} running "
                      f"{int(elapsed)}s...")
                warned = True
            if elapsed > limits["max_wait"]:
                raise MaxWaitExceeded(
                    f"job {job_id} exceeded max wait of "
                    f"{limits['max_wait']}s in status {status}")
            time.sleep(self.poll_interval)


def _now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _blocking_job_id(error_text: str) -> str | None:
    match = re.search(r'"blocking_job_id"\s*:\s*"([^"]+)"', error_text)
    return match.group(1) if match else None


def parse_json_block(text: str):
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text
    array = re.search(r"\[.*\]", raw, re.S)
    if array:
        return _json.loads(array.group(0))
    obj = re.search(r"\{.*\}", raw, re.S)
    if obj:
        parsed = _json.loads(obj.group(0))
        if isinstance(parsed, list):
            return parsed
        for key in ("mappings", "clauses", "results", "matrix", "items",
                    "data", "coverage"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
        return [parsed]
    head = re.sub(r"\s+", " ", (text or "")).strip()[:300]
    raise ValueError(
        f"no JSON object found in model response; response began: {head!r}")
