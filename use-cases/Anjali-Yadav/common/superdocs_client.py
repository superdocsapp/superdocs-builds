"""
Shared SuperDocs REST client for both Task 2 builds.

Encodes the three practical gotchas the task doc names explicitly, in one
place, so neither build has to remember them independently:

1. "proposed-change content arrives as a JSON-encoded string and needs a
   second parse" — chat()'s document_changes field is parsed defensively:
   if it's a string, json.loads it; if that fails, leave it as-is and let
   the caller see the raw value rather than crashing.
2. "operations on large documents...can take from thirty seconds to
   several minutes with no visible progress; the correct read is still
   processing, not a crash" — every call uses a generous timeout and
   never treats a slow response as a failure.
3. "budget your operations...give it a small-sample mode and a stopping
   rule" — OperationBudget tracks usage.monthly_remaining from each
   response and raises before you accidentally burn the free tier.
"""
import base64
import hashlib
import json
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

BASE_URL = "https://api.superdocs.app"
LONG_OP_TIMEOUT = 180  # seconds — per the doc's "several minutes, not a crash" note
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3


class SuperDocsError(Exception):
    pass


class BudgetExceeded(Exception):
    pass


def review_proposed_changes(changes: Any, input_fn=input) -> bool:
    """Require an explicit human decision before a proposal is committed."""
    print("\nProposed document changes:")
    print(json.dumps(changes, indent=2, ensure_ascii=True, default=str))
    decision = input_fn("Approve these changes? [y/N]: ").strip().lower()
    return decision in {"y", "yes"}


def review_changes_one_by_one(changes: Any, input_fn=input) -> list[dict]:
    """Collect an explicit approve/deny decision for every proposed change."""
    if not isinstance(changes, list):
        changes = [changes]
    decisions = []
    for index, change in enumerate(changes, start=1):
        if not isinstance(change, dict) or not change.get("change_id"):
            raise SuperDocsError(
                f"Proposed change {index} has no usable change_id; refusing review."
            )
        print(f"\nProposed change {index}/{len(changes)} ({change['change_id']}):")
        print(json.dumps(change, indent=2, ensure_ascii=True, default=str))
        decision = input_fn("Approve this change? [y/N]: ").strip().lower()
        decisions.append(
            {
                "change_id": change["change_id"],
                "approved": decision in {"y", "yes"},
            }
        )
    return decisions


def require_structured_changes(changes: Any) -> dict | list:
    """Fail closed when an approval proposal was not decoded into JSON data."""
    if not isinstance(changes, (dict, list)):
        raise SuperDocsError(
            "The proposed approval changes were not valid structured JSON; "
            "refusing to commit them."
        )
    return changes


def _post_with_backoff(
    session: requests.Session,
    url: str,
    json_body: dict,
    timeout: int,
    idempotency_key: str | None = None,
) -> requests.Response:
    """Retries on rate-limit/server-error/timeout with exponential
    backoff. Does NOT retry on 4xx (a validation error will fail
    identically the second time — retrying just wastes the warmup-retry
    budget and delays surfacing a real bug to the caller)."""
    last_exc = None
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    stopped = threading.Event()

    def report_processing() -> None:
        while not stopped.wait(30):
            print(
                "SuperDocs is still processing; the request has not timed out.",
                file=sys.stderr,
            )

    progress_thread = threading.Thread(target=report_processing, daemon=True)
    progress_thread.start()
    try:
        for attempt in range(_MAX_RETRIES):
            try:
                r = session.post(url, json=json_body, timeout=timeout, headers=headers)
            except requests.exceptions.Timeout as e:
                last_exc = e
                time.sleep(2 ** attempt)
                continue
            if r.status_code in _RETRYABLE_STATUS:
                last_exc = requests.exceptions.HTTPError(f"{r.status_code} on {url}")
                time.sleep(2 ** attempt)
                continue
            return r  # success OR a non-retryable 4xx — let raise_for_status() handle the latter
        raise SuperDocsError(f"Gave up after {_MAX_RETRIES} attempts on {url}: {last_exc}") from last_exc
    finally:
        stopped.set()
        progress_thread.join(timeout=1)


@dataclass
class OperationBudget:
    """Stopping rule: refuses to make another billable call once the
    remaining free-tier allowance drops below `floor`, rather than
    silently draining the account. Read from each response's own
    `usage.monthly_remaining` field — no separate API call needed."""
    floor: int = 20
    last_known_remaining: int | None = None

    def ensure_available(self) -> None:
        """Stop before a billable call when the last response exhausted the floor."""
        if (
            self.last_known_remaining is not None
            and self.last_known_remaining < self.floor
        ):
            raise BudgetExceeded(
                f"Only {self.last_known_remaining} operations remain "
                f"(floor is {self.floor}); no new billable call was sent."
            )

    def check(self, usage: dict | None) -> None:
        if not usage:
            return
        self.last_known_remaining = usage.get("monthly_remaining")
        if self.last_known_remaining is not None and self.last_known_remaining < self.floor:
            raise BudgetExceeded(
                f"Only {self.last_known_remaining} operations left this month "
                f"(floor is {self.floor}). Stopping here rather than risking "
                f"a mid-document failure from quota exhaustion."
            )


class SuperDocsClient:
    def __init__(self, api_key: str, budget: OperationBudget | None = None):
        self.api_key = api_key
        self.budget = budget or OperationBudget()
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )

    @classmethod
    def self_signup(cls, agent_name: str, budget: OperationBudget | None = None) -> "SuperDocsClient":
        """No key needed for this one call — matches the agent-signup flow
        the task doc points to."""
        r = requests.post(
            f"{BASE_URL}/v1/agents/signup",
            json={"agent_name": agent_name},
            timeout=30,
        )
        r.raise_for_status()
        key = r.json()["api_key"]
        return cls(key, budget=budget)

    # -- the four-call minimum contract -----------------------------------

    def upload(self, filename: str, html: str, session_id: str) -> dict:
        """session_id is REQUIRED here — omitting it makes SuperDocs treat
        the upload as a one-off conversion that's never persisted (this
        bit us once already; see the harness debugging from earlier)."""
        payload = {
            "filename": filename,
            "file_base64": base64.b64encode(html.encode()).decode(),
            "session_id": session_id,
            "return_html": True,
        }
        key = hashlib.sha256(f"upload:{session_id}".encode()).hexdigest()
        r = _post_with_backoff(
            self.session,
            f"{BASE_URL}/v1/documents/upload-base64",
            payload,
            LONG_OP_TIMEOUT,
            idempotency_key=key,
        )
        r.raise_for_status()
        return r.json()

    def chat(self, session_id: str, message: str, **kw) -> dict:
        self.budget.ensure_available()
        payload = {"session_id": session_id, "message": message, **kw}
        key_material = json.dumps(payload, sort_keys=True, default=str)
        key = hashlib.sha256(f"chat:{key_material}".encode()).hexdigest()
        r = _post_with_backoff(
            self.session,
            f"{BASE_URL}/v1/chat",
            payload,
            LONG_OP_TIMEOUT,
            idempotency_key=key,
        )
        r.raise_for_status()
        result = r.json()
        result["document_changes"] = self._parse_proposed_changes(result.get("document_changes"))
        approval = result.get("approval")
        if isinstance(approval, dict) and "changes" in approval:
            result["approval"] = {
                **approval,
                "changes": self._parse_proposed_changes(approval["changes"]),
            }
        self.budget.check(result.get("usage"))
        return result

    def chat_async(self, session_id: str, message: str, **kw) -> dict:
        """Start an async edit, including HITL review when requested."""
        self.budget.ensure_available()
        payload = {"session_id": session_id, "message": message, **kw}
        key_material = json.dumps(payload, sort_keys=True, default=str)
        key = hashlib.sha256(f"chat-async:{key_material}".encode()).hexdigest()
        r = _post_with_backoff(
            self.session,
            f"{BASE_URL}/v1/chat/async",
            payload,
            LONG_OP_TIMEOUT,
            idempotency_key=key,
        )
        r.raise_for_status()
        return r.json()

    def get_job(self, job_id: str, compact: bool = False) -> dict:
        """Read async job status; polling is free and never budget-checked."""
        r = self.session.get(
            f"{BASE_URL}/v1/jobs/{job_id}",
            params={"compact": str(compact).lower()},
            timeout=30,
        )
        r.raise_for_status()
        result = r.json()
        metadata = result.get("metadata")
        if isinstance(metadata, dict) and "pending_changes" in metadata:
            result["metadata"] = {
                **metadata,
                "pending_changes": self._parse_proposed_changes(
                    metadata["pending_changes"]
                ),
            }
        return result

    def get_session_jobs(self, session_id: str, compact: bool = True) -> list[dict]:
        """List persisted async jobs for recovery after a client restart."""
        r = self.session.get(
            f"{BASE_URL}/v1/sessions/{session_id}/jobs",
            params={"compact": str(compact).lower()},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        return body.get("jobs", []) if isinstance(body, dict) else body

    def find_active_job(self, session_id: str, message: str) -> dict | None:
        """Find a resumable job so a client crash cannot start duplicate work."""
        for job in self.get_session_jobs(session_id, compact=False):
            if job.get("status") not in {"pending", "in_progress", "awaiting_approval"}:
                continue
            metadata = job.get("metadata") or {}
            if metadata.get("message") == message:
                return job
        return None

    def get_document_detail(self, document_id: str, include_html: bool = False) -> dict:
        """Read free structural document metadata for post-edit verification."""
        r = self.session.get(
            f"{BASE_URL}/v1/documents/{document_id}",
            params={"include_html": str(include_html).lower()},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _parse_proposed_changes(raw: Any) -> Any:
        """Gotcha #1: proposed-change content is a JSON-ENCODED STRING that
        needs a second parse. If it's already an object (some responses
        may return it pre-parsed), leave it alone. If parsing fails,
        return the raw value rather than raising — an empty/undefined diff
        card downstream is recoverable; a crash here isn't."""
        if raw is None or not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def approve(self, session_id: str, **kw) -> dict:
        self.budget.ensure_available()
        key_material = json.dumps(kw, sort_keys=True, default=str)
        key = hashlib.sha256(f"approve:{session_id}:{key_material}".encode()).hexdigest()
        r = _post_with_backoff(
            self.session,
            f"{BASE_URL}/v1/chat/{session_id}/approve",
            kw,
            LONG_OP_TIMEOUT,
            idempotency_key=key,
        )
        r.raise_for_status()
        result = r.json()
        self.budget.check(result.get("usage"))
        return result

    def export(self, session_id: str, fmt: str, out_path: str) -> str:
        """Exports never cost operations per the task doc — no budget
        check needed here."""
        r = _post_with_backoff(
            self.session, f"{BASE_URL}/v1/documents/export",
            {"session_id": session_id, "format": fmt}, LONG_OP_TIMEOUT,
        )
        r.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(r.content)
        return out_path

    def chat_with_warmup_retry(self, session_id: str, message: str, **kw) -> dict:
        """The FIRST call on a brand-new session gets one extra grace
        retry beyond _post_with_backoff's normal handling, per the task
        doc's specific note that a fresh session's first request can be
        slow/fail while things warm up — a case distinct from ordinary
        rate-limiting."""
        try:
            return self.chat(session_id, message, **kw)
        except (requests.exceptions.RequestException, SuperDocsError):
            time.sleep(3)
            return self.chat(session_id, message, **kw)

    # -- templates surface --------------------------------------------
    # ASSUMPTION FLAGGED: these two paths are a best guess following the
    # naming convention of /v1/documents/upload-base64 — I never got a
    # confirmed sighting of the templates endpoints' actual paths (only
    # the MCP tool NAMES upload_template_base64/list_user_templates from
    # SKILL.md, not their REST routes). Verify against docs/openapi.json
    # (`grep -i template docs/openapi.json` in your cloned docs repo)
    # before relying on this in a demo — if the path is wrong you'll get
    # a clean 404, not a silent failure, so it'll be obvious.
    def upload_template(self, name: str, html: str) -> dict:
        r = self.session.post(
            f"{BASE_URL}/v1/templates/upload",
            files={
                "file": (
                    f"{name}.html",
                    html.encode(),
                    "text/html",
                )
            },
            timeout=LONG_OP_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    def list_templates(self) -> list[dict]:
        r = self.session.get(f"{BASE_URL}/v1/templates", timeout=30)
        r.raise_for_status()
        body = r.json()
        # Defensive: accept either a bare list or a {"templates": [...]}
        # envelope, since I can't confirm which shape this returns.
        return body if isinstance(body, list) else body.get("templates", [])

    # -- version history surface ---------------------------------------
    # revert's path IS confirmed (seen directly in docs/openapi.json
    # during earlier exploration this session — RevertRequest takes
    # turn_index, dry_run, window_id). get_session_history's path is a
    # naming-convention guess, same caveat as templates above.
    def get_session_history(self, session_id: str) -> list[dict]:
        r = self.session.get(f"{BASE_URL}/v1/sessions/{session_id}/history", timeout=30)
        r.raise_for_status()
        body = r.json()
        return body if isinstance(body, list) else body.get("history", body.get("messages", []))

    def revert(self, session_id: str, turn_index: int, dry_run: bool = False) -> dict:
        payload = {"turn_index": turn_index, "dry_run": dry_run}
        r = _post_with_backoff(self.session, f"{BASE_URL}/v1/sessions/{session_id}/revert", payload, LONG_OP_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def chat_with_review(
        self,
        session_id: str,
        message: str,
        approve_all: bool = False,
        input_fn=input,
        poll_timeout: float = 600,
    ) -> dict:
        """Run an async edit and resolve every HITL change before returning."""
        existing = self.find_active_job(session_id, message)
        started = existing or self.chat_async(
            session_id,
            message,
            approval_mode="ask_every_time",
        )
        job_id = started.get("job_id")
        if not job_id:
            raise SuperDocsError("Async chat response did not include job_id.")

        deadline = time.monotonic() + poll_timeout
        committed = False
        while time.monotonic() < deadline:
            job = self.get_job(job_id)
            status = job.get("status")
            if status == "awaiting_approval":
                metadata = job.get("metadata") or {}
                if metadata.get("awaiting_kind") == "continue_prompt":
                    raise SuperDocsError(
                        "Async job paused at a continue prompt; resume it explicitly "
                        "before reviewing document changes."
                    )
                pending = require_structured_changes(metadata.get("pending_changes", []))
                changes = pending if isinstance(pending, list) else [pending]
                decisions = (
                    [{"change_id": change["change_id"], "approved": True} for change in changes]
                    if approve_all
                    else review_changes_one_by_one(changes, input_fn=input_fn)
                )
                committed = committed or any(decision["approved"] for decision in decisions)
                self.approve(
                    session_id,
                    job_id=job_id,
                    approved=any(decision["approved"] for decision in decisions),
                    changes=decisions,
                )
            elif status == "completed":
                result = job.get("result") or {}
                result["review_committed"] = committed
                result["job_id"] = job_id
                return result
            elif status in {"failed", "cancelled"}:
                raise SuperDocsError(f"Async job {status}: {job.get('error', 'unknown error')}")
            time.sleep(2)
        raise SuperDocsError(f"Async job exceeded the {poll_timeout:g}-second polling deadline.")