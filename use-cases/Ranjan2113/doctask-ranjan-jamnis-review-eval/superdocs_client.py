"""Thin REST wrapper around the SuperDocs API.

Scope is deliberately narrow: what corpus building needs (verify a key, start
an async HITL edit, poll it, read the proposed changes) plus honest operation
accounting. Everything here is injectable so the test suite can exercise it
with no live key and no network -- see tests/test_superdocs_client.py.

Endpoint paths verified against docs.superdocs.app on 2026-08-14; see
PROGRESS.md A2 for the two places PLAN.md.pdf section 5 was wrong.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

DEFAULT_BASE_URL = "https://api.superdocs.app"

# The endpoint's own doc page says /v1/chat/async; the llms.txt index says
# /v1/chat-async. We try the documented one and fall back on a 404. A 404 is
# not billable, so the fallback costs nothing. (PROGRESS.md A2)
ASYNC_CHAT_PATHS = ("/v1/chat/async", "/v1/chat-async")

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
PAUSED_STATUSES = frozenset({"awaiting_approval"})


class SuperDocsError(RuntimeError):
    """Any non-recoverable failure talking to SuperDocs."""


class BudgetExceeded(SuperDocsError):
    """Raised *before* a call that would breach the operation ceiling.

    Deliberately raised pre-dispatch: a cap that is only checked after the
    fact is not a cap. (PROGRESS.md A5)
    """


class JobFailed(SuperDocsError):
    """The async job reached a terminal failure state."""


class JobTimeout(SuperDocsError):
    """The async job did not reach a decision state in time."""


@dataclass(frozen=True)
class Usage:
    """The server's own accounting for one call.

    We never infer operations from call counts -- retries, non-billable calls
    and free exports would all make a local counter lie. (PROGRESS.md A3)
    """

    ops_charged: int = 0
    was_billable: bool | None = None
    monthly_used: int | None = None
    monthly_limit: int | None = None
    monthly_remaining: int | None = None
    quota_exhausted: bool | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "Usage":
        if not payload:
            return cls()
        charged = payload.get("ops_charged")
        billable = payload.get("was_billable")
        if charged is None:
            # No explicit count. Trust was_billable if it is stated; if the
            # server said nothing at all, assume 0 rather than inventing spend.
            charged = 1 if billable else 0
        return cls(
            ops_charged=int(charged),
            was_billable=billable,
            monthly_used=payload.get("monthly_used"),
            monthly_limit=payload.get("monthly_limit"),
            monthly_remaining=payload.get("monthly_remaining"),
            quota_exhausted=payload.get("quota_exhausted"),
        )

    def describe(self) -> str:
        bits = [f"ops_charged={self.ops_charged}"]
        if self.was_billable is not None:
            bits.append(f"billable={self.was_billable}")
        if self.monthly_used is not None:
            limit = self.monthly_limit if self.monthly_limit is not None else "?"
            bits.append(f"monthly_used={self.monthly_used}/{limit}")
        if self.quota_exhausted:
            bits.append("QUOTA_EXHAUSTED")
        return "  ".join(bits)


@dataclass
class OpsLedger:
    """Append-only record of what each call cost.

    Kept separate from the client so a crash mid-run still leaves an auditable
    spend trail on disk -- the README has to report actual spend against the
    stated cap.
    """

    path: Path | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_ops(self) -> int:
        return sum(e.get("ops_charged", 0) for e in self.entries)

    def record(self, *, label: str, usage: Usage, note: str = "") -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "label": label,
            "note": note,
            **asdict(usage),
        }
        self.entries.append(entry)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")

    def load(self) -> None:
        """Re-read prior spend so a restart does not reset the budget to zero."""
        if self.path is None or not self.path.exists():
            return
        self.entries = [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class SuperDocsClient:
    """REST client with a hard operation ceiling.

    Args:
        api_key: sk_ key. Read from SUPERDOCS_API_KEY when omitted.
        max_operations: refuse to dispatch a billable call once spend reaches
            this. The pilot builds this client with max_operations=5.
        transport: anything with .request(method, url, **kw) -> Response.
            Tests pass a fake; production passes a requests.Session.
        sleep / clock: injected so polling tests run instantly.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        max_operations: int = 15,
        ledger: OpsLedger | None = None,
        transport: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        printer: Callable[[str], None] = print,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("SUPERDOCS_API_KEY")
        if not key:
            raise SuperDocsError(
                "No API key. Set SUPERDOCS_API_KEY in the environment or a .env "
                "file, or pass api_key= explicitly."
            )
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self.max_operations = max_operations
        self.ledger = ledger if ledger is not None else OpsLedger()
        self._transport = transport if transport is not None else requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._print = printer

    # -- plumbing ---------------------------------------------------------

    @property
    def ops_used(self) -> int:
        return self.ledger.total_ops

    @property
    def ops_remaining(self) -> int:
        return max(0, self.max_operations - self.ops_used)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _guard_budget(self, label: str, cost_estimate: int = 1) -> None:
        if self.ops_used + cost_estimate > self.max_operations:
            raise BudgetExceeded(
                f"{label!r} would put spend at "
                f"{self.ops_used + cost_estimate} operations, over the cap of "
                f"{self.max_operations}. Spent so far: {self.ops_used}. "
                f"Raise max_operations deliberately if this is intended."
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float = 120.0,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            return self._transport.request(
                method, url, headers=self._headers(), json=json_body, timeout=timeout
            )
        except requests.RequestException as exc:  # pragma: no cover - network only
            raise SuperDocsError(f"{method} {path} failed at transport level: {exc}") from exc

    @staticmethod
    def _json(response: requests.Response, context: str) -> dict[str, Any]:
        try:
            return response.json()
        except ValueError as exc:
            body = (response.text or "")[:400]
            raise SuperDocsError(f"{context}: response was not JSON: {body!r}") from exc

    def _report(self, label: str, usage: Usage, note: str = "") -> None:
        """Print and persist spend. Called after every call that can bill."""
        self.ledger.record(label=label, usage=usage, note=note)
        self._print(
            f"[ops] {label}: {usage.describe()}  "
            f"| run total {self.ops_used}/{self.max_operations}"
        )

    # -- API surface ------------------------------------------------------

    def verify_key(self) -> bool:
        """Cheap auth check. GET /v1/sessions is free (PLAN.md.pdf section 5)."""
        response = self._request("GET", "/v1/sessions", timeout=30.0)
        if response.status_code in (401, 403):
            return False
        if response.status_code >= 400:
            raise SuperDocsError(
                f"Key check got HTTP {response.status_code}: {(response.text or '')[:200]}"
            )
        return True

    def chat_async(
        self,
        *,
        message: str,
        session_id: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
        label: str = "chat_async",
    ) -> str:
        """Start an async edit and return its job_id.

        Billing happens on the job, not this dispatch, but the budget is
        guarded here because this is the call that commits us to the spend.
        """
        self._guard_budget(label)

        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "async_mode": True,
            "approval_mode": approval_mode,
        }
        if document_html is not None:
            body["document_html"] = document_html
        if model_tier:
            body["model_tier"] = model_tier
        if thinking_depth:
            body["thinking_depth"] = thinking_depth

        last_error = ""
        for path in ASYNC_CHAT_PATHS:
            response = self._request("POST", path, json_body=body)
            if response.status_code == 404:
                last_error = f"404 at {path}"
                continue  # try the alternate spelling; a 404 is not billable
            if response.status_code >= 400:
                raise SuperDocsError(
                    f"chat_async failed: HTTP {response.status_code} at {path}: "
                    f"{(response.text or '')[:300]}"
                )
            payload = self._json(response, "chat_async")
            job_id = payload.get("job_id")
            if not job_id:
                raise SuperDocsError(f"chat_async returned no job_id: {payload!r}")
            return job_id

        raise SuperDocsError(
            f"chat_async: no async endpoint responded ({last_error}). "
            f"Tried {list(ASYNC_CHAT_PATHS)}."
        )

    def get_job(self, job_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/v1/jobs/{job_id}", timeout=60.0)
        if response.status_code >= 400:
            raise SuperDocsError(
                f"get_job({job_id}) got HTTP {response.status_code}: "
                f"{(response.text or '')[:200]}"
            )
        return self._json(response, f"get_job({job_id})")

    def poll_job(
        self,
        job_id: str,
        *,
        timeout_s: float = 300.0,
        interval_s: float = 3.0,
        label: str = "job",
        assume_cost_if_unreported: int = 1,
    ) -> dict[str, Any]:
        """Poll until the job pauses for approval or finishes.

        Returns the full job payload. Reports usage exactly once, when the
        server first attaches a usage block.

        Observed on the live pilot (2026-08-14): a job that pauses at
        `awaiting_approval` has an EMPTY `result`, so no usage block exists
        yet -- the server appears to attach it only once the job completes.
        Trusting that silence would record 0 operations for work that almost
        certainly billed, and a budget guard that under-counts is worse than
        useless: it would happily authorize the next call.

        So when a job reaches a decision point having never reported usage, we
        record `assume_cost_if_unreported` as an ESTIMATE, flagged as such in
        the ledger. Over-counting is the safe direction against a hard cap.
        """
        started = self._clock()
        reported = False
        last_status = "<none>"

        while True:
            job = self.get_job(job_id)
            status = job.get("status", "")
            last_status = status or last_status

            usage_payload = (job.get("result") or {}).get("usage")
            if usage_payload and not reported:
                self._report(label, Usage.from_payload(usage_payload), note=f"job={job_id}")
                reported = True

            settled = (status in PAUSED_STATUSES and self._approval_is_real(job)) or (
                status in TERMINAL_STATUSES
            )
            if settled:
                if not reported and assume_cost_if_unreported:
                    self._report(
                        label,
                        Usage(ops_charged=assume_cost_if_unreported),
                        note=f"job={job_id} ESTIMATED: server reported no usage block "
                        f"at status={status!r}",
                    )
                if status == "failed":
                    raise JobFailed(f"job {job_id} failed: {job.get('error')!r}")
                return job

            if self._clock() - started > timeout_s:
                raise JobTimeout(
                    f"job {job_id} still {last_status!r} after {timeout_s:.0f}s"
                )
            self._sleep(interval_s)

    @staticmethod
    def _approval_is_real(job: dict[str, Any]) -> bool:
        """Distinguish a change-approval pause from a 'continue?' prompt.

        PLAN.md.pdf section 5 says to skip pauses where
        metadata.awaiting_kind == 'continue_prompt'. That field is not in the
        documented schema, so we honour it when present and never require it.
        (PROGRESS.md A2)
        """
        kind = (job.get("metadata") or {}).get("awaiting_kind")
        return kind != "continue_prompt"

    @staticmethod
    def extract_pending_changes(job: dict[str, Any]) -> list[dict[str, Any]]:
        """Pull proposed changes out of a job payload.

        The schema exposes them in three places depending on how the job
        resolved; first non-empty wins, deduped by change_id.
        """
        result = job.get("result") or {}
        doc_changes = result.get("document_changes") or {}
        candidates: Iterable[Any] = (
            (job.get("metadata") or {}).get("pending_changes"),
            doc_changes.get("pending_changes"),
            doc_changes.get("chunk_diffs"),
        )
        for group in candidates:
            if group:
                seen: set[str] = set()
                unique: list[dict[str, Any]] = []
                for change in group:
                    cid = change.get("change_id")
                    if cid and cid in seen:
                        continue
                    if cid:
                        seen.add(cid)
                    unique.append(change)
                return unique
        return []


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader. Avoids a python-dotenv dependency for 8 lines.

    Does not overwrite variables already set in the real environment.
    """
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
