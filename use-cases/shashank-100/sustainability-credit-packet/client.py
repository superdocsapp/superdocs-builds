"""SuperDocs REST client.

Three things this wrapper exists to get right, each learned from the task
document's own warnings:

1. **The double parse.** Proposed-change content arrives as a JSON-encoded
   string and needs a second parse. The task document names this "the single
   most common reason integrators see empty diff cards where every field reads
   as undefined". It is handled once, here, in `_parse_maybe_json`.

2. **Patience.** Operations on large documents can take from thirty seconds to
   several minutes with no visible progress. The correct read is still
   processing, not a crash. Timeouts are generous and async jobs are polled.

3. **Operation budget.** Every billable call is counted and logged, so a run
   can report what it spent -- and so a loop can never quietly drain the
   monthly allowance.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app")

# Long enough for the "thirty seconds to several minutes" case the task
# document warns about, short enough to fail eventually.
REQUEST_TIMEOUT = 300
POLL_INTERVAL = 3
POLL_CEILING = 600


class SuperDocsError(RuntimeError):
    """An API call failed in a way the caller cannot paper over."""


class QuotaExhausted(SuperDocsError):
    """The account is out of operations. Distinct so callers can stop cleanly."""


def _parse_maybe_json(value: Any) -> Any:
    """Parse a value that may be a JSON-encoded string.

    The API returns proposed-change payloads as strings containing JSON. A
    single parse leaves the caller holding a string it will index into as if it
    were an object, producing undefined everywhere. Parsing defensively here
    means no call site has to remember.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # A string that merely looks like JSON is still just a string.
        return value


@dataclass
class Change:
    """One proposed edit, already parsed and ready to review."""

    chunk_id: str
    operation: str
    old_html: str
    new_html: str
    document_id: str | None = None
    change_id: str | None = None
    status: str | None = None
    explanation: str | None = None

    @property
    def is_noop(self) -> bool:
        return self.old_html == self.new_html

    @property
    def awaiting_review(self) -> bool:
        """True when this change is still queued for a human decision."""
        return self.status in (None, "pending", "pending_review", "proposed")


@dataclass
class Usage:
    """What a run spent. The task document asks a run to report its cost."""

    calls: int = 0
    ops_charged: int = 0
    seconds: float = 0.0
    by_stage: dict[str, dict] = field(default_factory=dict)
    remaining: int | None = None

    def record(self, stage: str, ops: int, seconds: float) -> None:
        self.calls += 1
        self.ops_charged += ops
        self.seconds += seconds
        entry = self.by_stage.setdefault(stage, {"calls": 0, "ops": 0, "seconds": 0.0})
        entry["calls"] += 1
        entry["ops"] += ops
        entry["seconds"] += seconds

    def report(self) -> str:
        lines = [
            f"{self.calls} calls, {self.ops_charged} operations, {self.seconds:.1f}s total",
        ]
        for stage, entry in sorted(self.by_stage.items(), key=lambda kv: -kv[1]["seconds"]):
            lines.append(
                f"  {stage:28} {entry['calls']:2} calls  "
                f"{entry['ops']:2} ops  {entry['seconds']:6.1f}s"
            )
        if self.remaining is not None:
            lines.append(f"  operations remaining this month: {self.remaining}")
        return "\n".join(lines)


class SuperDocs:
    def __init__(self, api_key: str | None = None, *, budget: int | None = None):
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise SuperDocsError(
                "No API key. Set SUPERDOCS_API_KEY, or copy .env.example to .env."
            )
        self.usage = Usage()
        # A hard ceiling on operations for one run, so a bug cannot drain the
        # monthly allowance. None means no local limit.
        self.budget = budget
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self.api_key}"

    # ------------------------------------------------------------- transport
    def _call(self, method: str, path: str, *, stage: str, **kwargs) -> dict:
        if self.budget is not None and self.usage.ops_charged >= self.budget:
            raise QuotaExhausted(
                f"run budget of {self.budget} operations reached; stopping before spending more"
            )

        url = f"{BASE_URL}{path}"
        started = time.monotonic()
        try:
            response = self._session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.Timeout as exc:
            raise SuperDocsError(
                f"{stage}: no response after {REQUEST_TIMEOUT}s. Large documents can take "
                "several minutes; consider raising REQUEST_TIMEOUT rather than assuming a crash."
            ) from exc
        except requests.RequestException as exc:
            raise SuperDocsError(f"{stage}: request failed: {exc}") from exc
        elapsed = time.monotonic() - started

        # Quota exhaustion arrives as a 402, and sometimes as a 429 or 400
        # whose body says so. Both must raise QuotaExhausted: packet_cli gives
        # it its own exit code so a run can stop without burning the rest of
        # the allowance. The body is only inspected on an error response with
        # a textual content type -- a successful export is binary, and decoding
        # it here would read the whole payload just to search it.
        if response.status_code == 402:
            raise QuotaExhausted(f"{stage}: account is out of operations")
        if not response.ok:
            ctype = response.headers.get("content-type", "")
            if ("json" in ctype or ctype.startswith("text")) and \
                    "quota" in response.text.lower()[:400]:
                raise QuotaExhausted(
                    f"{stage}: HTTP {response.status_code} reports the operation allowance is spent"
                )
        if not response.ok:
            raise SuperDocsError(
                f"{stage}: HTTP {response.status_code} from {path} -- {response.text[:400]}"
            )

        # Exports return a binary body, not JSON.
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            self.usage.record(stage, 0, elapsed)
            return {"_binary": response.content, "_headers": dict(response.headers)}

        payload = response.json()
        usage = payload.get("usage") or {}
        ops = int(usage.get("ops_charged", 0) or 0)
        self.usage.record(stage, ops, elapsed)
        if usage.get("monthly_remaining") is not None:
            self.usage.remaining = usage["monthly_remaining"]
        if usage.get("quota_exhausted"):
            raise QuotaExhausted(f"{stage}: the account has run out of operations")
        return payload

    # ------------------------------------------------------------- endpoints
    def whoami(self) -> dict:
        return self._call("GET", "/v1/agents/whoami", stage="whoami")

    def upload(self, path: Path, session_id: str, *, open_mode: str = "background") -> dict:
        """Upload a file. Uses the upload path rather than inlining bytes.

        The task document asks for large real files to be handled through the
        upload path rather than in memory.
        """
        path = Path(path)
        with path.open("rb") as handle:
            return self._call(
                "POST",
                "/v1/documents/upload",
                stage="upload",
                files={"file": (path.name, handle)},
                data={"session_id": session_id, "open_mode": open_mode},
            )

    def chat(self, message: str, session_id: str, *, document_html: str | None = None,
             model_tier: str = "core", thinking_depth: str = "balanced",
             stage: str = "chat", **extra) -> dict:
        body = {
            "message": message,
            "session_id": session_id,
            "model_tier": model_tier,
            "thinking_depth": thinking_depth,
            "response_mode": "compact",
            **extra,
        }
        if document_html is not None:
            body["document_html"] = document_html
        return self._call("POST", "/v1/chat", stage=stage, json=body)

    def chat_async(self, message: str, session_id: str, *,
                   approval_mode: str = "ask_every_time",
                   model_tier: str = "core", thinking_depth: str = "balanced",
                   stage: str = "chat", **extra) -> dict:
        """Send an instruction that pauses for human approval.

        The card requires that a person reviews changes before they land, so
        the default here is ask_every_time -- the opposite of the API's own
        default of auto_approve.
        """
        body = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "model_tier": model_tier,
            "thinking_depth": thinking_depth,
            "response_mode": "compact",
            **extra,
        }
        started = self._call("POST", "/v1/chat/async", stage=stage, json=body)
        job_id = started.get("job_id")
        if not job_id:
            return started
        return self.wait_for_job(job_id, stage=stage)

    def job(self, job_id: str, *, stage: str = "job") -> dict:
        return self._call("GET", f"/v1/jobs/{job_id}", stage=stage)

    def wait_for_job(self, job_id: str, *, stage: str = "job",
                     until: tuple[str, ...] = ("awaiting_approval", "completed", "failed")) -> dict:
        """Poll a job until it settles.

        Long operations are normal here -- the task document warns they can run
        from thirty seconds to several minutes with no visible progress -- so
        this waits patiently rather than treating slowness as failure.
        """
        deadline = time.monotonic() + POLL_CEILING
        while True:
            payload = self.job(job_id, stage=f"{stage}:poll")
            status = payload.get("status")
            if status in until:
                return payload
            if time.monotonic() > deadline:
                raise SuperDocsError(
                    f"{stage}: job {job_id} still {status!r} after {POLL_CEILING}s"
                )
            time.sleep(POLL_INTERVAL)

    def wait_until_idle(self, session_id: str, *, stage: str = "settle") -> None:
        """Block until the session has no job still running.

        Approving returns as soon as the decisions are recorded, but the job
        keeps working for a moment afterwards. Sending the next instruction
        during that window gets a 409 session_busy, so callers wait here first.
        """
        deadline = time.monotonic() + POLL_CEILING
        while time.monotonic() < deadline:
            payload = self._call(
                "GET", f"/v1/jobs?session_id={session_id}", stage=f"{stage}:poll"
            )
            jobs = payload if isinstance(payload, list) else payload.get("jobs", [])
            # The session_id query parameter is not honoured by the endpoint,
            # so filter here rather than trusting the server to have done it.
            active = [
                j for j in jobs
                if isinstance(j, dict)
                and j.get("session_id") == session_id
                and j.get("status") in ("pending", "in_progress", "awaiting_approval")
            ]
            if not active:
                return
            time.sleep(POLL_INTERVAL)
        raise SuperDocsError(f"{stage}: session {session_id} still busy after {POLL_CEILING}s")

    def approve(self, session_id: str, changes: list[dict], *,
                job_id: str | None = None, feedback: str | None = None) -> dict:
        """Approve or reject proposed changes, one decision per change.

        Rejecting one change must not discard the rest, so decisions are always
        sent per chunk rather than as a single blanket verdict.
        """
        body: dict[str, Any] = {
            "approved": any(c.get("approved") for c in changes),
            "changes": changes,
        }
        # Undocumented but required: the approve endpoint 422s without the id
        # of the job whose changes are being decided.
        if job_id:
            body["job_id"] = job_id
        if feedback:
            body["feedback"] = feedback
        return self._call("POST", f"/v1/chat/{session_id}/approve", stage="approve", json=body)

    def export(self, session_id: str, fmt: str = "docx", **options) -> bytes:
        payload = self._call(
            "POST",
            "/v1/documents/export",
            stage="export",
            json={"session_id": session_id, "format": fmt, "options": options},
        )
        if "_binary" not in payload:
            raise SuperDocsError(f"export returned JSON, not a file: {str(payload)[:300]}")
        return payload["_binary"]

    # --------------------------------------------------------------- helpers
    def changes_from(self, response: dict) -> list[Change]:
        """Pull proposed changes out of a chat response, parsed and normalised.

        Handles both the single-document shape (`document_changes.chunk_diffs`)
        and the multi-document shape (`proposed_change_batch`), and applies the
        second parse wherever the payload arrived as a JSON string.
        """
        response = _parse_maybe_json(response)
        if not isinstance(response, dict):
            return []

        raw: list = []

        # An async job wraps the chat payload in `result`, and queues changes
        # awaiting review under `metadata.pending_changes`. Unwrap both so the
        # caller does not care whether the call was sync or async.
        metadata = _parse_maybe_json(response.get("metadata"))
        if isinstance(metadata, dict):
            queued = _parse_maybe_json(metadata.get("pending_changes"))
            if isinstance(queued, list):
                raw.extend(queued)
        result = _parse_maybe_json(response.get("result"))
        if isinstance(result, dict):
            response = {**result, **{k: v for k, v in response.items() if k != "result"}}

        batch = _parse_maybe_json(response.get("proposed_change_batch"))
        if isinstance(batch, dict):
            batch = batch.get("changes") or batch.get("items") or []
        if isinstance(batch, list):
            raw.extend(batch)

        document_changes = _parse_maybe_json(response.get("document_changes"))
        if isinstance(document_changes, dict):
            # The live API populates "changes" and "chunk_diffs"; when a run is
            # gated for review the queue arrives as "pending_changes". Take
            # whichever are present and de-duplicate by chunk below.
            for key in ("changes", "chunk_diffs", "pending_changes"):
                section = _parse_maybe_json(document_changes.get(key))
                if isinstance(section, list):
                    raw.extend(section)

        changes = []
        seen: set[tuple] = set()
        for item in raw:
            item = _parse_maybe_json(item)
            if not isinstance(item, dict):
                continue
            chunk_id = item.get("chunk_id") or item.get("id")
            if not chunk_id:
                continue
            fingerprint = (
                str(chunk_id),
                item.get("new_html") or item.get("after") or "",
                item.get("document_id"),
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            changes.append(
                Change(
                    chunk_id=str(chunk_id),
                    operation=item.get("operation", "update"),
                    old_html=item.get("old_html") or item.get("before") or "",
                    new_html=item.get("new_html") or item.get("after") or "",
                    document_id=item.get("document_id"),
                    change_id=item.get("change_id"),
                    status=item.get("status"),
                    explanation=item.get("ai_explanation") or item.get("explanation"),
                )
            )
        return changes
