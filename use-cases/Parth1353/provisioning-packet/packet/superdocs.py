"""The SuperDocs client.

Four calls carry this build — upload, chat, approve, export — and they are the
first four methods below. Everything after them is optional depth.

Three things learned the hard way (two of them from the task brief's own
warnings, one from watching it happen) are handled here rather than in calling
code:

* **Proposed-change content arrives JSON-encoded inside a JSON field.** It needs
  a second parse. Missing that is the documented reason integrators see diff
  cards where every field is ``undefined``. ``pending_changes`` does the double
  parse in one place so no caller can forget.
* **Operations on large documents can take minutes with no visible progress.**
  Every poll loop here has a generous ceiling and reports elapsed time as it
  goes, because "still processing" and "crashed" look identical otherwise.
* **Operations cost money.** Every billable call goes through ``_spend``, which
  counts against a per-run budget and refuses to exceed it. Exports and reads
  are free and are not counted.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Iterator
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
    """What this run spent.

    The brief's third practical note says to budget operations and learn it on
    day one, not day nine. `limit` is a stopping rule, not a warning.
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
    def seconds(self) -> float:
        """Time spent inside requests. Not the same as elapsed time."""
        return sum(op.seconds for op in self.operations)

    @property
    def elapsed(self) -> float:
        """Actual wall time since the ledger opened.

        Reported separately because the two differ by a lot and the difference
        matters: an async edit spends ~1s in the POST and ~12s being polled, so
        summing request latencies and calling it "wall_seconds" understated a
        real run by more than tenfold. The brief asks for timed-where-you-
        promise-fast; a timing number that quietly excludes the waiting is not
        that.
        """
        return time.monotonic() - self.started_at

    def record(self, kind: str, detail: str, *, billable: bool, seconds: float = 0.0) -> None:
        self.operations.append(Operation(kind, detail, billable, seconds))

    def check(self, kind: str) -> None:
        if self.billable >= self.limit:
            raise BudgetExceeded(
                f"operation budget of {self.limit} reached before {kind}",
                fix="raise --max-operations, or run with --only to build fewer documents",
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
            "elapsed_seconds": round(self.elapsed, 1),
            "in_request_seconds": round(self.seconds, 1),
            "budget": self.limit,
            "remaining": self.remaining,
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
        if not api_key or not api_key.startswith("sk_"):
            raise SuperDocsError(
                "SUPERDOCS_API_KEY is missing or does not look like a key",
                fix="set SUPERDOCS_API_KEY=sk_... in your environment or .env file. "
                "Create one at use.superdocs.app → Settings → API Keys.",
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.ledger = ledger or Ledger()
        # Content-Type is set per request, not on the client: a multipart
        # upload must be allowed to set its own boundary, and a client-level
        # application/json would silently corrupt it.
        self._client = client or httpx.Client(
            timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SuperDocs:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        url = f"{self.base_url}{path}"
        started = time.perf_counter()
        try:
            resp = self._client.request(method, url, **kw)
        except httpx.TimeoutException as exc:
            raise SuperDocsError(
                f"{method} {path} timed out",
                fix="large documents and deep model settings can take minutes. "
                "Use the async path (chat_async + poll) rather than a longer timeout.",
            ) from exc
        except httpx.HTTPError as exc:
            raise SuperDocsError(f"{method} {path} failed: {exc}") from exc
        finally:
            self._last_seconds = time.perf_counter() - started

        if resp.status_code >= 400:
            raise SuperDocsError(_explain(resp), status=resp.status_code, fix=_fix_for(resp))
        return resp

    def _json(self, method: str, path: str, body: dict | None = None) -> dict:
        resp = self._request(
            method, path, json=body, headers={"Content-Type": "application/json"}
        )
        if not resp.content:
            return {}
        return resp.json()

    def _spend(self, kind: str, detail: str) -> None:
        self.ledger.check(kind)

    # ==================================================================
    # The four calls the brief names as the minimum contract
    # ==================================================================

    def upload_document(
        self,
        path: Path | str,
        *,
        session_id: str,
        open_mode: str = "new_focused",
        return_html: bool = False,
    ) -> dict[str, Any]:
        """1/4 — upload. Parses the file into HTML where every block carries a
        ``data-chunk-id``, which is what makes later edits surgical.

        **Multipart, not base64, and that is the whole reason this build works.**

        ``open_mode`` is accepted only on the multipart endpoint. The base64
        endpoint always replaces the session's focused document, so uploading
        six documents to one session over base64 leaves you with one document
        and five discarded uploads — silently, because every call returns 200.
        The docs say this in a note on the multi-document page; I read it, built
        it wrong anyway, and only found out when a live run reported that the
        session contained a single document. See README, "What went wrong".

        The base64 path is kept for single-document callers via
        ``open_mode=None``, because it avoids a multipart encode.
        """
        path = Path(path)
        if self.ledger.dry_run:
            self.ledger.record("upload", path.name, billable=False)
            return {"dry_run": True, "filename": path.name, "session_id": session_id}

        self._spend("upload", path.name)
        if open_mode is None:
            result = self._json(
                "POST",
                "/documents/upload-base64",
                {
                    "filename": path.name,
                    "file_base64": base64.b64encode(path.read_bytes()).decode(),
                    "session_id": session_id,
                    "return_html": return_html,
                },
            )
        else:
            resp = self._request(
                "POST",
                "/documents/upload",
                files={"file": (path.name, path.read_bytes(), _media_type(path))},
                data={
                    "session_id": session_id,
                    "open_mode": open_mode,
                    "return_html": str(return_html).lower(),
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            result = resp.json()
        self.ledger.record("upload", path.name, billable=True, seconds=self._last_seconds)
        return result

    def chat(
        self,
        message: str,
        *,
        session_id: str,
        document_html: str | None = None,
        document_id: str | None = None,
        approval_mode: ApprovalMode = "approve_all",
        model_tier: ModelTier = "core",
        thinking_depth: str = "balanced",
        response_mode: str = "full",
    ) -> dict[str, Any]:
        """2/4 — chat. Synchronous; use ``chat_async`` when a human reviews."""
        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "model_tier": model_tier,
            "thinking_depth": thinking_depth,
            "response_mode": response_mode,
        }
        # Only send the document when the session does not already hold it —
        # re-sending on every turn is the most common way to lose chunk ids.
        if document_html is not None:
            body["document_html"] = document_html
        if document_id is not None:
            body["document_id"] = document_id

        if self.ledger.dry_run:
            self.ledger.record("chat", message[:70], billable=False)
            return {"dry_run": True, "message": message}
        self._spend("chat", message[:70])
        result = self._json("POST", "/chat", body)
        self.ledger.record("chat", message[:70], billable=True, seconds=self._last_seconds)
        return result

    def approve(
        self,
        session_id: str,
        job_id: str,
        *,
        approved: bool,
        change_id: str | None = None,
        changes: list[dict[str, Any]] | None = None,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """3/4 — approve.

        ``approved`` is required at the top level even for batch shapes; the API
        returns a bare 422 if it is missing, which is a confusing error for an
        obvious mistake. The signature makes it impossible to omit.
        """
        body: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if change_id:
            body["change_id"] = change_id
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

    def export(
        self,
        *,
        session_id: str | None = None,
        html: str | None = None,
        fmt: ExportFormat = "docx",
        filename: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """4/4 — export. Free: exports never cost an operation.

        Returns the bytes plus any non-fatal warnings, which arrive
        base64-encoded in ``X-Export-Warnings`` and are otherwise easy to miss —
        an image that 404'd or a diagram that failed to render is exactly the
        thing you want to know about before sending a pack to a customer.
        """
        if not session_id and not html:
            raise SuperDocsError("export needs either a session_id or html")
        body: dict[str, Any] = {"format": fmt, "options": {**(options or {})}}
        if filename:
            body["options"]["filename"] = filename
        if session_id:
            body["session_id"] = session_id
        if html is not None:
            body["html"] = html

        if self.ledger.dry_run:
            self.ledger.record("export", f"{filename or session_id}.{fmt}", billable=False)
            return b"", []

        resp = self._request("POST", "/documents/export", json=body)
        self.ledger.record(
            "export", f"{filename or session_id}.{fmt}", billable=False,
            seconds=self._last_seconds,
        )
        warnings: list[dict[str, Any]] = []
        raw = resp.headers.get("X-Export-Warnings")
        if raw:
            try:
                warnings = json.loads(base64.b64decode(raw))
            except Exception:
                log.debug("could not decode X-Export-Warnings: %r", raw[:120])
        return resp.content, warnings

    # ==================================================================
    # Async + human-in-the-loop
    # ==================================================================

    def chat_async(
        self,
        message: str,
        *,
        session_id: str,
        document_id: str | None = None,
        approval_mode: ApprovalMode = "ask_every_time",
        model_tier: ModelTier = "core",
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
            self.ledger.record("chat_async", message[:70], billable=False)
            return "dry-run-job"
        self._spend("chat_async", message[:70])
        result = self._json("POST", "/chat/async", body)
        self.ledger.record("chat_async", message[:70], billable=True, seconds=self._last_seconds)
        job_id = result.get("job_id")
        if not job_id:
            raise SuperDocsError(f"chat/async returned no job_id: {json.dumps(result)[:200]}")
        return job_id

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._json("GET", f"/jobs/{job_id}")

    def wait_for_job(
        self,
        job_id: str,
        *,
        timeout: float = 600.0,
        interval: float = 2.0,
        on_tick=None,
    ) -> dict[str, Any]:
        """Poll until the job stops or pauses for a human.

        Returns on ``awaiting_approval`` as well as on terminal states — the
        caller has to branch on ``metadata.awaiting_kind`` anyway, because the
        same status covers "review these changes" and "this large edit paused,
        shall I continue".
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
                    fix="this is slow, not necessarily broken. Raise the timeout, or "
                    "cancel with POST /v1/jobs/{job_id}/cancel and retry with a smaller edit.",
                )
            time.sleep(interval)

    @staticmethod
    def pending_changes(job: dict[str, Any]) -> list[dict[str, Any]]:
        """The proposed changes on a paused job, correctly parsed.

        Two shapes reach a caller. Polling ``/jobs/{id}`` gives
        ``metadata.pending_changes`` as a real array. The SSE stream gives a
        ``proposed_change_batch`` event whose ``content`` is a JSON-encoded
        *string* that needs a second parse — the single most common reason a
        diff card renders with every field ``undefined``. Both are handled.
        """
        meta = job.get("metadata") or {}
        raw = meta.get("pending_changes")

        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict):
            raw = raw.get("changes", [])
        if raw:
            return list(raw)

        batch = meta.get("proposed_change_batch") or job.get("content")
        if isinstance(batch, str):
            try:
                batch = json.loads(batch)
            except json.JSONDecodeError:
                return []
        if isinstance(batch, str):  # doubly encoded
            batch = json.loads(batch)
        if isinstance(batch, dict):
            return list(batch.get("changes", []))
        return []

    @staticmethod
    def awaiting_kind(job: dict[str, Any]) -> str:
        """``continue_prompt`` and a change review share one status.

        Calling /approve on a continue-prompt pause is rejected with 409 and
        vice versa, so every caller must branch on this first.
        """
        return ((job.get("metadata") or {}).get("awaiting_kind")) or "approval"

    def continue_chat(self, session_id: str, job_id: str, *, keep_going: bool) -> dict[str, Any]:
        return self._json(
            "POST", f"/chat/{session_id}/continue", {"job_id": job_id, "continue": keep_going}
        )

    # ==================================================================
    # Multi-document, templates, images — the optional depth
    # ==================================================================

    def list_session_documents(self, session_id: str, *, include_html: bool = False) -> dict:
        """The session's document roster — and the authoritative source of
        document ids. Free, so a build reads it back rather than trusting the
        shape of an upload response."""
        suffix = "?include_html=true" if include_html else ""
        return self._json("GET", f"/sessions/{session_id}/documents{suffix}")

    def focus_document(self, session_id: str, document_id: str) -> dict:
        return self._json("POST", f"/sessions/{session_id}/documents/{document_id}/focus")

    def document_detail(self, document_id: str) -> dict:
        """Free structural read. The right way to verify an edit — exporting
        just to check what changed is slow and pointless."""
        return self._json("GET", f"/documents/{document_id}")

    def list_documents(self) -> dict:
        return self._json("GET", "/documents")

    def upload_template(self, path: Path | str) -> dict:
        path = Path(path)
        return self._json(
            "POST",
            "/templates/upload-base64",
            {
                "filename": path.name,
                "file_base64": base64.b64encode(path.read_bytes()).decode(),
            },
        )

    def list_templates(self) -> dict:
        return self._json("GET", "/templates")

    def upload_image(self, path: Path | str, *, content_type: str = "image/png") -> str:
        path = Path(path)
        result = self._json(
            "POST",
            "/documents/images/upload-base64",
            {
                "image_base64": base64.b64encode(path.read_bytes()).decode(),
                "filename": path.name,
                "content_type": content_type,
            },
        )
        url = result.get("url") or result.get("image_url") or result.get("src")
        if not url:
            raise SuperDocsError(f"image upload returned no url: {json.dumps(result)[:200]}")
        return url

    def whoami(self) -> dict:
        """Tier and remaining monthly operations. Free, and worth calling before
        a build so the budget is real rather than assumed."""
        return self._json("GET", "/agents/whoami")

    def usage(self) -> dict:
        return self._json("GET", "/users/me/limits")


# ---------------------------------------------------------------------------


def _media_type(path: Path) -> str:
    return {
        ".html": "text/html", ".htm": "text/html", ".md": "text/markdown",
        ".txt": "text/plain", ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(path.suffix.lower(), "application/octet-stream")


def _explain(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        detail = body.get("detail") or body.get("message") or body.get("error") or body
    except Exception:
        detail = resp.text[:400]
    return f"SuperDocs returned {resp.status_code}: {detail}"


def _fix_for(resp: httpx.Response) -> str | None:
    return {
        401: "the key value is just sk_... — no quotes, and no literal 'Bearer ' inside it",
        403: "this key does not have access to that resource; check it is the right account",
        404: "check the session_id in the path matches the one used on the original request",
        409: "the job is in a state that rejects this call — branch on metadata.awaiting_kind "
        "before choosing /approve or /continue",
        413: "the payload is too large for an inline POST; use the pre-signed upload flow",
        422: "a required field is missing. On /approve, top-level `approved` is required even "
        "for batch decisions",
        429: "monthly operation limit or rate limit reached; check GET /v1/users/me/limits",
    }.get(resp.status_code)


def iter_sse(lines: Iterator[str]) -> Iterator[tuple[str, dict]]:
    """Parse an SSE byte stream into (event, data) pairs.

    Not used by the default build (polling is simpler for a CLI and equally
    valid per the docs) but kept because it is the piece most integrators get
    wrong, and because the double-parse of ``proposed_change_batch.content``
    lives on this path too.
    """
    event = "message"
    for line in lines:
        line = line.rstrip("\n")
        if not line:
            event = "message"
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            payload = line[5:].strip()
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if event == "proposed_change_batch" and isinstance(data.get("content"), str):
                data["content"] = json.loads(data["content"])
            yield event, data
