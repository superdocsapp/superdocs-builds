"""Thin client for the four-call SuperDocs contract, plus the free key
check and the coverage-judge question.

One class, no logic beyond transport, typed errors, and the operation
budget. Everything the engine decides stays in engine/ — this file only
carries requests and counts what they cost.
"""
import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from superdocs.errors import (
    AuthenticationFailed,
    BudgetExceeded,
    MalformedResponse,
    NotConfigured,
    RequestFailed,
    ResourceNotFound,
    TransportError,
)

BASE_URL = "https://api.superdocs.app/v1"
REQUEST_TIMEOUT_SECONDS = 180  # long jobs poll separately; single calls stay bounded
POLL_INTERVAL_SECONDS = 3
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


def read_env(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        raise NotConfigured(
            f"{env_path} not found — copy .env.example to .env and put your "
            f"SUPERDOCS_API_KEY in it"
        )
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


class OperationBudget:
    """Hard cap on billable operations per run — one run being the whole
    cycle from draft to export — counted from the server's own usage
    fields, never from our assumptions. The count lives in memory while a
    command runs and in run_state.json between commands, so every command
    of one run picks up where the last one stopped."""

    def __init__(self, max_ops: int, spent: int = 0):
        self.max_ops = max_ops
        self.spent = spent
        self.remaining: int | None = None

    def ensure_can_spend(self) -> None:
        if self.spent >= self.max_ops:
            raise BudgetExceeded(
                f"this run already spent {self.spent} of {self.max_ops} allowed "
                f"operations — stopping before the next billable call; raise "
                f"MAX_OPS_PER_RUN in .env only if you mean to spend more"
            )

    def record(self, payload: dict, billable: bool = False) -> None:
        usage = payload.get("usage") or {}
        charged = usage.get("ops_charged")
        if charged is None:
            # /chat/async bills but sends no usage block, so a call we know
            # is billable costs at least one operation. A reported 0 is left
            # at 0: free judge questions must not be counted against the cap.
            charged = 1 if (billable or usage.get("was_billable")) else 0
        # the server reports what is left: a promotional grant when one is
        # active (that is the bucket being drawn down), else the monthly plan
        promotions = [
            p.get("ops_remaining")
            for p in (usage.get("promotions") or [])
            if isinstance(p, dict) and p.get("ops_remaining") is not None
        ]
        if promotions:
            self.remaining = sum(int(n) for n in promotions)
        elif usage.get("monthly_remaining") is not None:
            self.remaining = int(usage["monthly_remaining"])
        self.spent += int(charged)


class SuperDocsClient:
    def __init__(self, api_key: str, budget: OperationBudget, transport=None):
        if not api_key or api_key == "sk_your_key_here":
            raise NotConfigured(
                "SUPERDOCS_API_KEY is missing or still the placeholder — put "
                "your real key in .env (never in .env.example)"
            )
        self.api_key = api_key
        self.budget = budget
        self._transport = transport or self._http

    def _http(self, method: str, path: str, body: dict | None) -> dict:
        request = urllib.request.Request(
            BASE_URL + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code in (401, 403):
                raise AuthenticationFailed(
                    f"SuperDocs rejected the key ({e.code}) — check the key in "
                    f".env or make a new one in the app"
                ) from e
            if e.code == 404:
                raise ResourceNotFound(f"{path} answered 404: {detail}") from e
            raise RequestFailed(f"{method} {path} answered {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise TransportError(
                f"{method} {path} did not complete: {e} — check connectivity "
                f"and retry"
            ) from e
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise MalformedResponse(
                f"{method} {path} answered 2xx but the body is not JSON: "
                f"{raw[:200]!r}"
            ) from e

    def _call(self, method: str, path: str, body: dict | None = None, billable: bool = False) -> dict:
        if billable:
            self.budget.ensure_can_spend()
        payload = self._transport(method, path, body)
        if not isinstance(payload, dict):
            raise MalformedResponse(f"{method} {path} returned {type(payload).__name__}, not an object")
        self.budget.record(payload, billable)
        return payload

    def verify_key(self) -> dict:
        # GET /sessions is the documented key check: free, and unlike
        # /users/* it accepts sk_ API keys (docs.superdocs.app/account/api-keys)
        return self._call("GET", "/sessions")

    def upload_document(self, filename: str, text: str, session_id: str) -> dict:
        return self._call(
            "POST",
            "/documents/upload-base64",
            {
                # the field is file_base64 — content_base64 is the classic 422
                "filename": filename,
                "file_base64": base64.b64encode(text.encode("utf-8")).decode(),
                "session_id": session_id,
                "return_html": False,
            },
        )

    def ask(self, session_id: str, message: str, model_tier: str) -> str:
        """One synchronous chat question; returns the model's reply text.
        Billable. Used for judgement, never for document edits."""
        payload = self._call(
            "POST",
            "/chat",
            {
                "message": message,
                "session_id": session_id,
                "approval_mode": "ask_every_time",
                "response_mode": "compact",
                "model_tier": model_tier,
            },
            billable=True,
        )
        reply = payload.get("response")
        if not isinstance(reply, str) or not reply.strip():
            raise MalformedResponse(
                "chat answered without a text reply — fields: "
                f"{sorted(payload.keys())}"
            )
        return reply

    def send_edit_instruction(self, session_id: str, message: str, model_tier: str) -> dict:
        return self._call(
            "POST",
            "/chat/async",
            {
                "message": message,
                "session_id": session_id,
                "approval_mode": "ask_every_time",
                "response_mode": "compact",
                "model_tier": model_tier,
            },
            billable=True,
        )

    def upload_attachment(self, filename: str, file_bytes: bytes, session_id: str) -> dict:
        """Attach a source document to the session, so the model can search
        the full original rather than only our quoted excerpts."""
        return self._call(
            "POST",
            "/attachments/upload-base64",
            {
                "filename": filename,
                "file_base64": base64.b64encode(file_bytes).decode(),
                "session_id": session_id,
            },
        )

    def attachment_status(self, session_id: str) -> dict:
        return self._call("GET", f"/attachments/status/{session_id}")

    def get_job(self, job_id: str) -> dict:
        return self._call("GET", f"/jobs/{job_id}")

    def wait_for_decision_or_end(self, job_id: str, max_wait_seconds: int) -> dict:
        """Poll until the job needs a decision or ends. Long silence is
        'still processing', not a crash — but the wait stays bounded."""
        waited = 0
        while True:
            job = self.get_job(job_id)
            status = job.get("status")
            if status == "awaiting_approval" or status in TERMINAL_JOB_STATUSES:
                return job
            if waited >= max_wait_seconds:
                raise TransportError(
                    f"job {job_id} still '{status}' after {max_wait_seconds}s — "
                    f"the server may be busy; re-run to resume polling the same job"
                )
            time.sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS

    def decide_changes(
        self, session_id: str, job_id: str, decisions: list[dict]
    ) -> dict:
        return self._call(
            "POST",
            f"/chat/{session_id}/approve",
            {
                # top-level approved is required even when per-change
                # decisions carry the real answer — omitting it is a 422
                "job_id": job_id,
                "approved": True,
                "changes": decisions,
            },
        )

    def export_document(self, session_id: str, format: str) -> bytes:
        """Export returns the file's bytes, not JSON — free of operations."""
        request = urllib.request.Request(
            BASE_URL + "/documents/export",
            data=json.dumps({"session_id": session_id, "format": format}).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise RequestFailed(
                f"export ({format}) answered {e.code}: {detail}"
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise TransportError(
                f"export ({format}) did not complete: {e} — exports are free, "
                f"safe to retry"
            ) from e
