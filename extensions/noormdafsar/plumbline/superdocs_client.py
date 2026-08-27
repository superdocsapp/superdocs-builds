"""A small SuperDocs REST client. Python standard library only, no dependencies.

Covers the four-call contract the task names -- upload, chat, approve, export --
plus async jobs (the HITL gate needs them), template registry upload, and the
operational habits the docs ask for:

* warm-up retry: the first request in a fresh session can be slow or fail;
  it is retried once before anyone panics
* 429 handling: application 429s honor Retry-After; plain-text infrastructure
  429s back off with jitter
* the second-parse gotcha: pending_changes can arrive as a JSON-encoded string
  and needs a second json.loads -- the single most common integrator bug,
  per the task brief. parse_pending_changes() handles both shapes.
* an operations ledger fed from the usage block of every response, so the
  batch can enforce a stopping rule instead of discovering the cap at 429
"""

from __future__ import annotations

import http.client
import json
import os
import random
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app")

# Sync chat can legitimately take minutes on big edits ("still processing, not
# a crash" -- the docs are explicit). Our documents are small; 300s is generous.
TIMEOUT_S = 300


class SuperDocsError(RuntimeError):
    """An API failure with the cause named, never a bare status code."""


class QuotaExhausted(SuperDocsError):
    pass


def _read_dotenv(path: Path) -> str:
    """Minimal .env reader -- KEY=value, # comments, optional quotes.

    Deliberately hand-rolled: this project has no dependencies, and pulling in
    python-dotenv to parse four lines would be the only pip install in it.
    """
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "SUPERDOCS_API_KEY":
                return value.strip().strip("'\"")
    except OSError:
        pass
    return ""


def load_api_key() -> str:
    """Three places, in order, so the obvious thing works wherever you put it:

    1. SUPERDOCS_API_KEY in the environment
    2. a .env file beside this module
    3. ~/.superdocs/agent_credentials.json (the agent-signup store)
    """
    key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    if key:
        return key

    key = _read_dotenv(Path(__file__).resolve().parent / ".env")
    if key:
        return key

    cred = Path.home() / ".superdocs" / "agent_credentials.json"
    if cred.exists():
        try:
            key = json.loads(cred.read_text(encoding="utf-8")).get("api_key", "")
            if key:
                return key
        except (OSError, json.JSONDecodeError):
            pass

    raise SuperDocsError(
        "No API key found. Do one of:\n"
        "  * copy .env.example to .env and put your key in it, or\n"
        "  * export SUPERDOCS_API_KEY=sk_..., or\n"
        "  * let an agent create one: POST /v1/agents/signup\n"
        "    (https://docs.superdocs.app/introduction/agent-signup)"
    )


def parse_pending_changes(raw):
    """The documented gotcha: proposed-change content can arrive as a
    JSON-encoded string and needs a second parse; the final result is already
    an object. Handle both without caring which one this deployment sends."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, dict):  # some shapes wrap the list
        raw = raw.get("changes", raw.get("pending_changes", []))
    return list(raw)


class Client:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or load_api_key()
        self.ops_spent = 0          # billed operations observed this process
        self.monthly_remaining = None  # last value the API reported

    # ------------------------------------------------------------- plumbing
    def _request(self, method: str, path: str, body: dict | None = None,
                 raw_body: bytes | None = None, headers: dict | None = None,
                 expect_binary: bool = False, tries: int = 3):
        url = BASE + path
        h = {"Authorization": f"Bearer {self.api_key}"}
        data = None
        if body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        elif raw_body is not None:
            data = raw_body
        if headers:
            h.update(headers)

        last = ""
        for attempt in range(tries):
            req = urllib.request.Request(url, data=data, headers=h, method=method)
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                    payload = resp.read()
                    if expect_binary:
                        return payload
                    return json.loads(payload) if payload else {}
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", errors="replace")
                retry_after = e.headers.get("Retry-After")
                if e.code == 429:
                    if retry_after:  # application 429: quota or cooldown
                        wait = int(float(retry_after))
                        if wait > 300:
                            # monthly quota exhausted -- waiting is not a strategy
                            raise QuotaExhausted(
                                f"429 from {path}: {text[:200]} "
                                f"(Retry-After {wait}s -- the monthly quota is gone; "
                                f"stop the batch rather than spin)"
                            )
                        time.sleep(wait)
                        continue
                    # infrastructure 429: plain text, no header -> jittered backoff
                    time.sleep((2 ** attempt) + random.random())
                    last = f"429 (infrastructure): {text[:120]}"
                    continue
                if e.code in (502, 503, 504) and attempt + 1 < tries:
                    # includes the documented first-request warm-up hiccup
                    time.sleep(3 * (attempt + 1))
                    last = f"{e.code}: {text[:120]}"
                    continue
                raise SuperDocsError(f"{method} {path} -> HTTP {e.code}: {text[:400]}")
            except (urllib.error.URLError, http.client.HTTPException,
                    ConnectionError, TimeoutError, OSError) as e:
                # Deliberately broad. An earlier version caught only URLError and
                # TimeoutError, so a bare http.client.RemoteDisconnected -- a
                # server hanging up mid-request, which happens -- escaped the
                # retry loop and took the whole batch down with it, mid-account.
                # A transient blip should cost a retry, never a run.
                if attempt + 1 < tries:
                    time.sleep(3 * (attempt + 1))
                    last = f"{type(e).__name__}: {e}"
                    continue
                raise SuperDocsError(
                    f"{method} {path} failed after {tries} tries: "
                    f"{last or f'{type(e).__name__}: {e}'}")
        raise SuperDocsError(f"{method} {path} failed after {tries} tries: {last}")

    def _track_usage(self, payload: dict):
        usage = payload.get("usage") or (payload.get("result") or {}).get("usage")
        if isinstance(usage, dict):
            self.ops_spent += int(usage.get("ops_charged") or 0)
            if usage.get("monthly_remaining") is not None:
                self.monthly_remaining = usage["monthly_remaining"]

    # ------------------------------------------------------------- the four
    def chat(self, message: str, session_id: str, document_html: str | None = None,
             approval_mode: str = "approve_all", model_tier: str | None = None) -> dict:
        body = {"message": message, "session_id": session_id, "approval_mode": approval_mode}
        if document_html is not None:
            body["document_html"] = document_html
        if model_tier:
            body["model_tier"] = model_tier
        out = self._request("POST", "/v1/chat", body)
        self._track_usage(out)
        return out

    def chat_async(self, message: str, session_id: str, document_html: str | None = None,
                   approval_mode: str = "ask_every_time", model_tier: str | None = None) -> str:
        body = {"message": message, "session_id": session_id, "approval_mode": approval_mode}
        if document_html is not None:
            body["document_html"] = document_html
        if model_tier:
            body["model_tier"] = model_tier
        out = self._request("POST", "/v1/chat/async", body)
        return out["job_id"]

    def job(self, job_id: str) -> dict:
        out = self._request("GET", f"/v1/jobs/{job_id}")
        self._track_usage(out)
        return out

    def wait_for_job(self, job_id: str, session_id: str | None = None,
                     poll_s: float = 3.0, timeout_s: float = 900) -> dict:
        """Poll until the job is terminal OR needs a human/continue decision.

        Handles both flavours of awaiting_approval the docs warn about:
        a continue_prompt (large edit paused) is auto-continued, a HITL pause
        is returned to the caller -- that one belongs to a person.
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            j = self.job(job_id)
            status = j.get("status")
            if status in ("completed", "failed", "cancelled"):
                return j
            if status == "awaiting_approval":
                kind = (j.get("metadata") or {}).get("awaiting_kind")
                sess = session_id or j.get("session_id")
                if kind == "continue_prompt" and sess:
                    self._request("POST", f"/v1/chat/{sess}/continue",
                                  {"job_id": job_id, "continue": True})
                else:
                    return j  # a human decision -- never made here
            time.sleep(poll_s)
        raise SuperDocsError(f"job {job_id} still not settled after {timeout_s}s")

    def approve(self, session_id: str, job_id: str, decisions: list[dict],
                approved_default: bool, feedback: str | None = None) -> dict:
        # Top-level `approved` is REQUIRED even for batch shapes -- omitting it
        # is the documented 422 trap.
        body = {"job_id": job_id, "approved": approved_default, "changes": decisions}
        if feedback:
            body["feedback"] = feedback
        return self._request("POST", f"/v1/chat/{session_id}/approve", body)

    def cancel_job(self, job_id: str) -> dict:
        return self._request("POST", f"/v1/jobs/{job_id}/cancel", {})

    def export_text(self, session_id: str, fmt: str = "markdown") -> str:
        """Export straight to a string, for previewing in the review console."""
        blob = self._request("POST", "/v1/documents/export",
                             {"session_id": session_id, "format": fmt},
                             expect_binary=True)
        return blob.decode("utf-8", errors="replace")

    def export(self, session_id: str, fmt: str, out_path: Path,
               filename: str | None = None) -> Path:
        """Exports are free and do not cost operations. Export early, export often."""
        body = {"session_id": session_id, "format": fmt}
        if filename:
            body["options"] = {"filename": filename}
        blob = self._request("POST", "/v1/documents/export", body, expect_binary=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(blob)
        return out_path

    # -------------------------------------------------------------- extras
    def upload_template(self, path: Path) -> dict:
        """Register a reusable template (multipart, built by hand -- stdlib only)."""
        boundary = uuid.uuid4().hex
        blob = path.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: text/html\r\n\r\n"
        ).encode() + blob + f"\r\n--{boundary}--\r\n".encode()
        return self._request(
            "POST", "/v1/templates/upload", raw_body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def list_templates(self) -> dict:
        return self._request("GET", "/v1/templates")

    def whoami(self) -> dict:
        return self._request("GET", "/v1/agents/whoami")
