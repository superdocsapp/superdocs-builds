"""The SuperDocs client.

Adapted from the client in my Task 2 build for this round
(``use-cases/Parth1353/provisioning-packet``) and trimmed to what this tool
actually calls. It is copied rather than imported because CONTRIBUTING.md asks
each project to stand alone in its own folder, and because a reviewer should be
able to run this one without the other.

Four things are handled here rather than in calling code, all of them learned
against the live API:

* **Multipart upload, never base64.** ``upload-base64`` silently *replaces* a
  session's focused document and returns no document id, so uploading five
  runbooks to one session over it leaves you with one runbook, four discarded
  uploads and five ``200``s. Ids are read back from the session roster rather
  than trusted from the upload response.
* **Reading a document back is a roster call, not an export.**
  ``POST /documents/export`` takes a ``session_id`` and no ``document_id``, so
  in a multi-document session it returns whichever document is focused. Using
  it to check an edit landed silently checks the same file every time.
  ``GET /sessions/{id}/documents?include_html=true`` returns each document's
  own body, in one free call.
* **Proposed changes arrive JSON-encoded inside a JSON field** on the SSE
  path. ``pending_changes`` does the second parse in one place.
* **Operations cost money.** Every billable call goes through the ledger,
  which is a stopping rule and not a warning. Exports and reads are free and
  are not counted.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://api.superdocs.app/v1"

ApprovalMode = Literal["approve_all", "ask_every_time"]
ModelTier = Literal["core", "turbo", "pro", "max"]
ExportFormat = Literal["docx", "pdf", "html", "markdown", "txt"]


class SuperDocsError(RuntimeError):
    """Carries the cause and, where we know it, the fix."""

    def __init__(self, message: str, *, status: int | None = None, fix: str | None = None):
        super().__init__(message if not fix else f"{message}\n  → {fix}")
        self.status = status
        self.fix = fix


class BudgetExceeded(SuperDocsError):
    pass


@dataclass
class Operation:
    kind: str
    detail: str
    billable: bool
    seconds: float = 0.0


@dataclass
class Ledger:
    """What this run spent, and the point at which it refuses to spend more.

    ``limit`` is a hard stop checked *before* each billable call, not a budget
    reported afterwards. A tool that runs inside an editor and is triggered by
    a file save has to be incapable of quietly emptying an account.
    """

    limit: int = 40
    dry_run: bool = False
    operations: list[Operation] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)

    @property
    def billable(self) -> int:
        return sum(1 for op in self.operations if op.billable)

    @property
    def remaining(self) -> int:
        return self.limit - self.billable

    @property
    def elapsed(self) -> float:
        """Wall time, which is not the sum of request latencies.

        Reported separately because they differ by more than tenfold: an async
        edit spends about a second in the POST and then a dozen being polled.
        Summing request time and calling it the run's duration understates it
        badly enough to be a lie.
        """
        return time.monotonic() - self.started_at

    @property
    def in_request_seconds(self) -> float:
        return sum(op.seconds for op in self.operations)

    def record(self, kind: str, detail: str, *, billable: bool, seconds: float = 0.0) -> None:
        self.operations.append(Operation(kind, detail, billable, seconds))

    def check(self, kind: str) -> None:
        if self.billable >= self.limit:
            raise BudgetExceeded(
                f"operation budget of {self.limit} reached before {kind}",
                fix="raise --max-operations, or narrow the run with --only",
            )

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for op in self.operations:
            if op.billable:
                by_kind[op.kind] = by_kind.get(op.kind, 0) + 1
        return {
            "billable_operations": self.billable,
            "free_calls": len(self.operations) - self.billable,
            "by_kind": by_kind,
            "budget": self.limit,
            "remaining": self.remaining,
            "elapsed_seconds": round(self.elapsed, 1),
            "in_request_seconds": round(self.in_request_seconds, 1),
        }


class SuperDocs:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        ledger: Ledger | None = None,
        timeout: float = 180.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.startswith(("sk_", "lce_")):
            raise SuperDocsError(
                "SUPERDOCS_API_KEY is missing or does not look like a key",
                fix="set SUPERDOCS_API_KEY=sk_... in your environment or a .env file. "
                "Create one at use.superdocs.app → Settings → API Keys.",
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.ledger = ledger or Ledger()
        self._last_seconds = 0.0
        # No client-level Content-Type: a multipart upload has to set its own
        # boundary, and a pinned application/json corrupts it silently.
        self._client = client or httpx.Client(
            timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SuperDocs:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        started = time.perf_counter()
        try:
            resp = self._client.request(method, url, **kw)
        except httpx.TimeoutException as exc:
            raise SuperDocsError(
                f"{method} {path} timed out",
                fix="large documents can take minutes. Use the async path rather than "
                "a longer timeout.",
            ) from exc
        except httpx.HTTPError as exc:
            raise SuperDocsError(f"{method} {path} failed: {exc}") from exc
        finally:
            self._last_seconds = time.perf_counter() - started

        if resp.status_code >= 400:
            raise SuperDocsError(_explain(resp), status=resp.status_code, fix=_fix_for(resp))
        return resp

    def _json(self, method: str, path: str, body: dict | None = None) -> dict:
        resp = self._request(method, path, json=body, headers={"Content-Type": "application/json"})
        if not resp.content:
            return {}
        return resp.json()

    # -- the calls this tool makes ----------------------------------------

    def upload_markdown(
        self, *, filename: str, text: str, session_id: str, open_mode: str = "new_focused"
    ) -> dict[str, Any]:
        """Put a document in a session. Multipart, always.

        ``open_mode`` is accepted only on the multipart endpoint, and it is the
        difference between a session with five documents and a session with one.
        """
        if self.ledger.dry_run:
            self.ledger.record("upload", filename, billable=False)
            return {"dry_run": True, "filename": filename}
        self.ledger.check("upload")
        resp = self._request(
            "POST",
            "/documents/upload",
            files={"file": (filename, text.encode("utf-8"), "text/markdown")},
            data={"session_id": session_id, "open_mode": open_mode, "return_html": "false"},
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        self.ledger.record("upload", filename, billable=True, seconds=self._last_seconds)
        return resp.json()

    def chat_async(
        self,
        message: str,
        *,
        session_id: str,
        document_id: str | None = None,
        approval_mode: ApprovalMode = "ask_every_time",
        model_tier: ModelTier = "pro",
        thinking_depth: str = "balanced",
    ) -> str:
        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "async_mode": True,
            "approval_mode": approval_mode,
            "model_tier": model_tier,
            "thinking_depth": thinking_depth,
        }
        if document_id:
            body["document_id"] = document_id
        if self.ledger.dry_run:
            self.ledger.record("edit", message[:70], billable=False)
            return "dry-run-job"
        self.ledger.check("edit")
        result = self._json("POST", "/chat/async", body)
        self.ledger.record("edit", message[:70], billable=True, seconds=self._last_seconds)
        job_id = result.get("job_id")
        if not job_id:
            raise SuperDocsError(f"chat/async returned no job_id: {json.dumps(result)[:200]}")
        return str(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._json("GET", f"/jobs/{job_id}")

    def wait_for_job(
        self,
        job_id: str,
        *,
        timeout: float = 420.0,
        interval: float = 2.0,
        on_tick: Any = None,
    ) -> dict[str, Any]:
        """Poll until the job stops or pauses for a human.

        Returns on ``awaiting_approval`` as well as on terminal states, because
        that status covers both "review these changes" and "this large edit
        paused, shall I continue" and the caller has to branch on
        ``metadata.awaiting_kind`` either way.
        """
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(job_id)
            status = job.get("status")
            if on_tick:
                on_tick(status, job)
            if status in {"completed", "failed", "cancelled", "awaiting_approval"}:
                return job
            if time.monotonic() > deadline:
                raise SuperDocsError(
                    f"job {job_id} still {status} after {timeout:.0f}s",
                    fix="slow is not necessarily broken. Raise --poll-timeout, or cancel "
                    "with POST /v1/jobs/{job_id}/cancel and retry with a narrower change.",
                )
            time.sleep(interval)

    def approve(
        self,
        session_id: str,
        job_id: str,
        *,
        approved: bool,
        changes: list[dict[str, Any]] | None = None,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """Top-level ``approved`` is required even for batch shapes, and is
        unused when every change carries its own decision. Omitting it returns
        a bare 422, so the signature makes it impossible to omit."""
        body: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if changes is not None:
            body["changes"] = changes
        if feedback:
            body["feedback"] = feedback
        if self.ledger.dry_run:
            self.ledger.record("approve", job_id, billable=False)
            return {"dry_run": True}
        result = self._json("POST", f"/chat/{session_id}/approve", body)
        self.ledger.record("approve", job_id, billable=False, seconds=self._last_seconds)
        return result

    def continue_chat(self, session_id: str, job_id: str, *, keep_going: bool) -> dict[str, Any]:
        return self._json(
            "POST", f"/chat/{session_id}/continue", {"job_id": job_id, "continue": keep_going}
        )

    def session_documents(self, session_id: str, *, include_html: bool = False) -> dict:
        """The roster — and the only authoritative source of document ids.

        Free. With ``include_html`` it also returns each document's own body,
        which is how this tool reads an edit back without paying for an export
        and without the focused-document trap.
        """
        suffix = "?include_html=true" if include_html else ""
        return self._json("GET", f"/sessions/{session_id}/documents{suffix}")

    def export_html(self, html: str, *, fmt: ExportFormat = "markdown") -> tuple[bytes, list[dict]]:
        """Convert a document body to another format. Free.

        Ad-hoc HTML export rather than session export on purpose: session
        export has no ``document_id`` and would return whichever document
        happens to be focused.
        """
        if self.ledger.dry_run:
            self.ledger.record("export", fmt, billable=False)
            return b"", []
        resp = self._request(
            "POST",
            "/documents/export",
            json={"html": html, "format": fmt, "options": {}},
            headers={"Content-Type": "application/json"},
        )
        self.ledger.record("export", fmt, billable=False, seconds=self._last_seconds)
        warnings: list[dict[str, Any]] = []
        raw = resp.headers.get("X-Export-Warnings")
        if raw:
            try:
                warnings = json.loads(base64.b64decode(raw))
            except Exception:
                log.debug("could not decode X-Export-Warnings: %r", raw[:120])
        return resp.content, warnings

    def whoami(self) -> dict:
        return self._json("GET", "/agents/whoami")

    def promotions(self) -> dict:
        return self._json("GET", "/users/me/promotions")

    def remaining_operations(self) -> tuple[int | None, str]:
        """How many operations this account can actually draw, and from where.

        Two endpoints have to be added together, and the docs point at only one
        of them. ``whoami`` reports the *plan* quota: on this account it says
        free, 500 a month, 0 used — while ``/users/me/promotions`` shows 9,837
        operations remaining on an active grant, which is what every call so
        far has actually been drawn from.

        An agent told to budget against ``whoami`` alone would believe it had
        500 operations when it had ten thousand, and would refuse work it could
        do. Reported to SuperDocs; worked around here rather than repeated.
        """
        total = 0
        sources: list[str] = []
        try:
            quota = (self.whoami() or {}).get("quota") or {}
            plan = quota.get("remaining")
            if isinstance(plan, int):
                total += plan
                sources.append(f"{plan} on the {quota.get('tier', 'plan')} plan")
        except SuperDocsError:
            return None, "unknown"
        try:
            for grant in (self.promotions() or {}).get("active") or []:
                left = grant.get("ops_remaining")
                if isinstance(left, int):
                    total += left
                    sources.append(f"{left} from {grant.get('name', 'a promotion')}")
        except SuperDocsError:
            sources.append("promotional grants unknown")
        return total, " + ".join(sources) or "unknown"

    # -- parsing helpers ---------------------------------------------------

    @staticmethod
    def pending_changes(job: dict[str, Any]) -> list[dict[str, Any]]:
        """The proposed changes on a paused job, correctly parsed.

        Polling gives ``metadata.pending_changes`` as a real array; the SSE
        stream gives a ``proposed_change_batch`` whose ``content`` is a
        JSON-encoded *string* needing a second parse. Both are handled, because
        missing the second parse is the documented reason integrators see diff
        cards where every field is ``undefined``.
        """
        meta = job.get("metadata") or {}
        raw = meta.get("pending_changes")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = None
        if isinstance(raw, dict):
            raw = raw.get("changes", [])
        if raw:
            return list(raw)

        batch = meta.get("proposed_change_batch") or job.get("content")
        for _ in range(2):  # doubly encoded on at least one path
            if isinstance(batch, str):
                try:
                    batch = json.loads(batch)
                except json.JSONDecodeError:
                    return []
        if isinstance(batch, dict):
            return list(batch.get("changes", []))
        return []

    @staticmethod
    def awaiting_kind(job: dict[str, Any]) -> str:
        """``continue_prompt`` and a change review share one status, and calling
        the wrong endpoint returns a bare 409."""
        return ((job.get("metadata") or {}).get("awaiting_kind")) or "approval"

    @staticmethod
    def document_html(roster: dict, document_id: str) -> str | None:
        for doc in roster.get("documents") or []:
            if doc.get("document_id") == document_id:
                return doc.get("html")
        return None


# ---------------------------------------------------------------------------


def _explain(resp: httpx.Response) -> str:
    """The status, the machine-readable code, and the prose — in that order.

    ``error_code`` is the part worth keeping. SuperDocs' 409s are genuinely
    different animals — ``session_busy`` is "wait or use another session",
    while a continue-prompt 409 means "you called the wrong endpoint" — and
    the prose alone does not let a caller or a log tell them apart.
    """
    code = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            code = body.get("error_code") or body.get("code")
            detail = body.get("detail") or body.get("message") or body.get("error") or body
            if isinstance(detail, dict):
                detail = json.dumps(detail)[:400]
        else:
            detail = str(body)[:400]
    except Exception:
        detail = resp.text[:400]
    prefix = f"SuperDocs returned {resp.status_code}"
    if code:
        prefix += f" [{code}]"
    return f"{prefix}: {detail}"


def _fix_for(resp: httpx.Response) -> str | None:
    # The two 409s mean opposite things and need opposite actions, so the
    # machine-readable code decides before the status does.
    try:
        code = (resp.json() or {}).get("error_code") if resp.status_code == 409 else None
    except Exception:
        code = None
    if code == "session_busy":
        return (
            "another job is still active in this session — usually an earlier docsync run "
            "that was interrupted while its edits were parked at the approval gate. Decide "
            "or discard that batch (`docsync approve`, or docsync_discard over MCP). A "
            "fresh checkout gets its own sessions, so this only bites the same workspace."
        )
    return {
        401: "the key value is just sk_... — no quotes, and no literal 'Bearer ' inside it",
        403: "this key does not have access to that resource",
        404: "check the session id in the path matches the one used on the original request",
        409: "the job is in a state that rejects this call — branch on "
        "metadata.awaiting_kind before choosing /approve or /continue",
        413: "the document is too large for an inline POST",
        422: "a required field is missing. On /approve, top-level `approved` is required "
        "even for batch decisions",
        429: "monthly operation limit or rate limit reached; check GET /v1/agents/whoami",
    }.get(resp.status_code)


def load_env(*candidates: Path) -> None:
    """Read a .env if present. No dependency, no surprises, no overwrite."""
    for candidate in candidates:
        if not candidate or not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            import os

            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return
