"""SuperDocs client — one interface, two implementations.

Everything here follows behaviour observed on the live API on 2026-08-14,
not behaviour read from documentation. The observations that shaped this
module, each verified on the wire:

* **`metadata.pending_changes` entries are already objects.** Do NOT parse
  them again. The second-parse gotcha applies to
  `metadata.intermediate_responses[].content` where `type` is
  `"proposed_change_batch"` — that field really is a JSON-encoded string.
  Getting these two the wrong way round is the documented cause of diff
  cards where every field reads as `undefined`.
* **`get_job(compact=True)` drops `pending_changes` entirely**, despite the
  tool description claiming pending-change ids survive. So the polling loop
  polls compact for status and fetches once non-compact on arrival.
* **Cost:** upload, export, polling and approval are all free. One
  `chat_async` turn is one operation, covering up to 25 sections.
* **`get_account_status` is not a budget gauge** — it reports `used: 0`
  even after a billed operation whenever a promo bucket is active. True
  spend comes from `result.usage.ops_charged` on a completed job.
* **Errors** are structured: 404 ``{'detail': 'Job not found'}``; 400
  ``{'detail': 'Job is not awaiting approval (status: completed)'}``. The
  latter means re-approving an applied change is refused server-side
  rather than double-applied.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_ENDPOINT = "https://api.superdocs.app/mcp/"

#: Statuses a job can report. `awaiting_approval` is the human gate.
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class SuperDocsError(Exception):
    """Base class for SuperDocs client errors."""


class AuthError(SuperDocsError):
    """No usable API key."""


class ToolError(SuperDocsError):
    """The server refused a tool call. Carries the server's own detail."""

    def __init__(self, tool: str, status: int | None, detail: str) -> None:
        self.tool, self.status, self.detail = tool, status, detail
        super().__init__(
            f"SuperDocs tool {tool!r} failed"
            + (f" (HTTP {status})" if status else "")
            + f": {detail}"
        )


class JobFailed(SuperDocsError):
    """A job reached a terminal state that is not `completed`."""


@dataclass
class ProposedChange:
    """One proposed edit, awaiting a human decision."""

    change_id: str
    chunk_id: str
    document_id: str
    old_html: str
    new_html: str
    operation: str
    explanation: str

    @classmethod
    def from_pending(cls, raw: dict[str, Any]) -> "ProposedChange":
        # Already an object on the wire. No second parse here — that is the
        # trap; see the module docstring.
        return cls(
            change_id=raw["change_id"],
            chunk_id=raw.get("chunk_id", ""),
            document_id=raw.get("document_id", ""),
            old_html=raw.get("old_html", ""),
            new_html=raw.get("new_html", ""),
            operation=raw.get("operation", "edit"),
            explanation=raw.get("ai_explanation", ""),
        )


@dataclass
class JobState:
    job_id: str
    status: str
    progress: int = 0
    pending_changes: list[ProposedChange] = field(default_factory=list)
    ops_charged: int = 0
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SuperDocsClient(Protocol):
    """The four-call contract, plus the polling the HITL flow needs."""

    def upload(self, session_id: str, filename: str, content: str) -> dict[str, Any]: ...
    def chat_async(self, session_id: str, message: str) -> str: ...
    def get_job(self, job_id: str, compact: bool = True) -> JobState: ...
    def approve(self, session_id: str, job_id: str, change_id: str, approved: bool,
                feedback: str | None = None) -> None: ...
    def export(self, session_id: str, fmt: str = "html") -> str: ...
    def session_html(self, session_id: str) -> str: ...


def _parse_batch_events(raw_job: dict[str, Any]) -> list[dict[str, Any]]:
    """Decode `intermediate_responses[].content` for proposed-change batches.

    This is the field that genuinely needs a second parse — it is a
    JSON-encoded string, unlike `pending_changes`. Malformed entries are
    skipped rather than raising: progress events are diagnostics, and a
    diagnostic must never take down a run.
    """
    out: list[dict[str, Any]] = []
    meta = raw_job.get("metadata") or {}
    for ev in meta.get("intermediate_responses") or []:
        if ev.get("type") != "proposed_change_batch":
            continue
        content = ev.get("content")
        if not isinstance(content, str):
            continue
        try:
            out.append(json.loads(content))
        except json.JSONDecodeError:
            continue
    return out


class McpSuperDocsClient:
    """Talks to the live SuperDocs MCP server over Streamable HTTP.

    The API key is read from the ``SUPERDOCS_API_KEY`` environment variable
    and is never written to disk, a log, or an error message. Not exercised
    by the offline test suite by design — the suite must run without a key.
    """

    def __init__(self, api_key: str | None = None, endpoint: str = DEFAULT_ENDPOINT,
                 timeout: int = 120) -> None:
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY", "")
        if not self.api_key:
            raise AuthError(
                "no SuperDocs API key — set the SUPERDOCS_API_KEY environment "
                "variable to an sk_ key from use.superdocs.app "
                "(Settings → API Keys), or use FakeSuperDocsClient for "
                "offline work"
            )
        self.endpoint = endpoint
        self.timeout = timeout
        self._rpc_id = 0

    def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        self._rpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # structured server errors
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ToolError(tool, exc.code, detail) from None
        except urllib.error.URLError as exc:
            raise ToolError(tool, None, f"network error: {exc.reason}") from None

        return self._unwrap(tool, body)

    @staticmethod
    def _unwrap(tool: str, body: str) -> Any:
        """Pull the tool result out of a JSON or SSE-framed response."""
        text = body
        if body.lstrip().startswith("event:") or "\ndata:" in body:
            parts = [
                ln[len("data:"):].strip()
                for ln in body.splitlines()
                if ln.startswith("data:")
            ]
            text = parts[-1] if parts else body
        try:
            env = json.loads(text)
        except json.JSONDecodeError:
            raise ToolError(tool, None, f"unparseable response: {text[:200]}") from None

        if isinstance(env, dict) and "error" in env:
            raise ToolError(tool, None, json.dumps(env["error"])[:500])

        result = env.get("result", env) if isinstance(env, dict) else env

        # A failed tool call comes back as a *successful* JSON-RPC response
        # carrying `isError: true`, with the detail in a text block — verified
        # on the wire: an unknown job id returns HTTP 200 and
        # {"content":[{"type":"text","text":"Error calling tool 'get_job':
        #  HTTP error 404: Not Found - {'detail': 'Job not found'}"}],
        #  "isError":true}
        # Treating that as data is how a caller ends up parsing an error
        # string as a document.
        if isinstance(result, dict) and result.get("isError"):
            detail = ""
            for block in result.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    detail = block.get("text", "")
                    break
            status = None
            m = re.search(r"HTTP error (\d{3})", detail)
            if m:
                status = int(m.group(1))
            raise ToolError(tool, status, detail[:500] or "tool reported isError")

        # MCP wraps tool output in content blocks; unwrap the text payload.
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            for block in result["content"]:
                if block.get("type") == "text":
                    raw = block.get("text", "")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return raw
        return result

    # -- the four-call contract -----------------------------------------

    def upload(self, session_id: str, filename: str, content: str) -> dict[str, Any]:
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        return self._call(
            "upload_document_base64",
            {"filename": filename, "file_base64": b64,
             "session_id": session_id, "return_html": True},
        )

    def chat_async(self, session_id: str, message: str) -> str:
        res = self._call(
            "chat_async",
            {"session_id": session_id, "message": message,
             "approval_mode": "ask_every_time", "response_mode": "compact",
             "thinking_depth": "balanced"},
        )
        job_id = res.get("job_id") if isinstance(res, dict) else None
        if not job_id:
            raise ToolError("chat_async", None, f"no job_id in response: {res!r}"[:300])
        return job_id

    def get_job(self, job_id: str, compact: bool = True) -> JobState:
        raw = self._call("get_job", {"job_id": job_id, "compact": compact})
        return _job_state_from_raw(job_id, raw)

    def approve(self, session_id: str, job_id: str, change_id: str, approved: bool,
                feedback: str | None = None) -> None:
        args: dict[str, Any] = {
            "session_id": session_id, "job_id": job_id,
            "change_id": change_id, "approved": approved,
        }
        if feedback:
            args["feedback"] = feedback
        self._call("approve_change", args)

    def export(self, session_id: str, fmt: str = "html") -> str:
        res = self._call("export_document", {"session_id": session_id, "format": fmt})
        return res if isinstance(res, str) else json.dumps(res)

    def session_html(self, session_id: str) -> str:
        """Stored HTML, WITH chunk ids — the correct surface for byte proof.

        Exports strip `data-chunk-id`, so comparing exports would silently
        compare the wrong thing.
        """
        res = self._call(
            "get_session_history",
            {"session_id": session_id, "include_document_html": True},
        )
        state = (res or {}).get("document_state") or {}
        return state.get("html_content") or ""


def _job_state_from_raw(job_id: str, raw: dict[str, Any]) -> JobState:
    meta = raw.get("metadata") or {}
    pend = meta.get("pending_changes") or []
    result = raw.get("result") or {}
    usage = (result.get("usage") or {}) if isinstance(result, dict) else {}
    return JobState(
        job_id=job_id,
        status=raw.get("status", "unknown"),
        progress=raw.get("progress", 0) or 0,
        pending_changes=[ProposedChange.from_pending(p) for p in pend],
        ops_charged=usage.get("ops_charged", 0) or 0,
        error=raw.get("error"),
        raw=raw,
    )


def wait_for(client: SuperDocsClient, job_id: str, want: set[str],
             timeout: float = 300.0, interval: float = 2.0,
             sleep=time.sleep) -> JobState:
    """Poll until the job reaches one of `want`, or a terminal state.

    Polls compact (cheap, and polling is free) then fetches once
    non-compact on arrival, because compact suppresses `pending_changes`.
    Silence for tens of seconds is normal: large documents legitimately
    take minutes with no visible progress.
    """
    deadline = time.monotonic() + timeout
    while True:
        state = client.get_job(job_id, compact=True)
        if state.status in want or state.status in TERMINAL_STATUSES:
            full = client.get_job(job_id, compact=False)
            if full.status == "failed":
                raise JobFailed(
                    f"job {job_id} failed: {full.error or 'no detail given'}"
                )
            return full
        if time.monotonic() > deadline:
            raise JobFailed(
                f"job {job_id} did not reach {sorted(want)} within {timeout:.0f}s "
                f"(last status {state.status!r}, progress {state.progress}) — "
                f"raise the timeout, or check the job in the SuperDocs UI"
            )
        sleep(interval)


# -- offline fake --------------------------------------------------------


class FakeSuperDocsClient:
    """An offline stand-in that reproduces the real state machine.

    It replays the shapes observed on the wire, including the two error
    behaviours that matter: an unknown job id raises, and re-approving an
    already-applied change is refused rather than double-applied.

    Edits are applied by exact `old_html` → `new_html` replacement, which
    is what makes the surgical-precision proof meaningful: anything the
    edit did not name is untouched by construction, exactly as the real
    server behaves.
    """

    def __init__(self, fail_on_chat: bool = False) -> None:
        self.docs: dict[str, str] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.ops_charged = 0
        self.calls: list[tuple[str, str]] = []  # (tool, session_id)
        self.fail_on_chat = fail_on_chat
        self._n = 0

    def _next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n:04d}"

    def upload(self, session_id: str, filename: str, content: str) -> dict[str, Any]:
        self.calls.append(("upload", session_id))  # free
        # The real server assigns a data-chunk-id to every block element on
        # upload; local files arrive without them. Simulating that is what
        # makes chunk-scoped editing testable offline.
        self.docs[session_id] = self._assign_chunk_ids(content)
        return {"session_id": session_id, "filename": filename,
                "chunks_count": content.count("data-chunk-id"),
                "version_id": self._next("ver"), "persisted": True}

    def _assign_chunk_ids(self, html: str) -> str:
        """Give every block element a stable chunk id, as the server does."""
        import re

        counter = {"n": 0}
        block = re.compile(
            r"<(?P<tag>h[1-6]|p|li|td|th)(?P<attrs>|\s[^>]*)>", re.IGNORECASE
        )

        def add(m: re.Match) -> str:
            if "data-chunk-id" in m.group("attrs"):
                return m.group(0)
            counter["n"] += 1
            return (
                f'<{m.group("tag")}{m.group("attrs")} '
                f'data-chunk-id="fake-chunk-{counter["n"]:03d}">'
            )

        return block.sub(add, html)

    def stage_changes(self, session_id: str, edits: list[tuple[str, str, str]]) -> None:
        """Queue the edits the next `chat_async` should propose.

        Each edit is (chunk_id, old_html, new_html). Tests use this to
        drive the flow deterministically without a model in the loop.
        """
        self.jobs.setdefault("_staged", {})[session_id] = edits

    def chat_async(self, session_id: str, message: str) -> str:
        self.calls.append(("chat_async", session_id))
        if self.fail_on_chat:
            raise ToolError("chat_async", 500, "simulated upstream failure")
        job_id = self._next("job")
        staged = self.jobs.get("_staged", {}).get(session_id, [])
        if not staged:
            # No pre-staged edits: interpret the instruction, the way the
            # real model would. This keeps `apply --fake` a genuine
            # end-to-end exercise, and it doubles as a check that our
            # instruction is precise enough to be acted on mechanically.
            staged = self._plan_from_instruction(session_id, message)
        pending = [
            {"change_id": self._next("chg"), "chunk_id": cid, "document_id": "doc_primary",
             "old_html": old, "new_html": new, "operation": "edit",
             "ai_explanation": "proposed correction"}
            for cid, old, new in staged
        ]
        self.jobs[job_id] = {
            "session_id": session_id, "status": "awaiting_approval", "progress": 86,
            "pending": pending, "decisions": {}, "message": message, "billed": False,
        }
        return job_id

    def _plan_from_instruction(self, session_id: str,
                               message: str) -> list[tuple[str, str, str]]:
        """Derive edits from our own instruction format.

        Only the named value inside the named chunk is touched — the same
        discipline the real edit is asked for — so a fake run exercises the
        surgical guarantee rather than assuming it.
        """
        import re

        html = self.docs.get(session_id, "")
        chunk_re = re.compile(
            r'<(?P<tag>[a-zA-Z][\w-]*)\b[^>]*\bdata-chunk-id="(?P<cid>[^"]+)"[^>]*>'
            r"(?P<body>.*?)</(?P=tag)>",
            re.DOTALL,
        )
        wanted = re.findall(
            r'replace the value "(?P<old>[^"]+)" with "(?P<new>[^"]+)"', message
        )
        edits: list[tuple[str, str, str]] = []
        used: set[str] = set()
        for old, new in wanted:
            for m in chunk_re.finditer(html):
                cid = m.group("cid")
                if cid in used or old not in m.group("body"):
                    continue
                whole = m.group(0)
                edits.append((cid, whole, whole.replace(old, new, 1)))
                used.add(cid)
                break
        return edits

    def get_job(self, job_id: str, compact: bool = True) -> JobState:
        job = self.jobs.get(job_id)
        if job is None:
            raise ToolError("get_job", 404, "{'detail': 'Job not found'}")
        # Mirrors the real server: compact suppresses pending_changes.
        pend = [] if compact else job["pending"]
        raw = {
            "status": job["status"], "progress": job["progress"],
            "metadata": {"pending_changes": pend},
            "result": {"usage": {"ops_charged": 1 if job["billed"] else 0}},
            "error": job.get("error"),
        }
        return _job_state_from_raw(job_id, raw)

    def approve(self, session_id: str, job_id: str, change_id: str, approved: bool,
                feedback: str | None = None) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            raise ToolError("approve_change", 404, "{'detail': 'Job not found'}")
        if job["status"] != "awaiting_approval":
            raise ToolError(
                "approve_change", 400,
                f"{{'detail': 'Job is not awaiting approval "
                f"(status: {job['status']})'}}",
            )
        job["decisions"][change_id] = approved
        if len(job["decisions"]) >= len(job["pending"]):
            self._apply(job)

    def _apply(self, job: dict[str, Any]) -> None:
        html = self.docs.get(job["session_id"], "")
        for change in job["pending"]:
            if job["decisions"].get(change["change_id"]):
                # Exact replacement: nothing else can move.
                html = html.replace(change["old_html"], change["new_html"], 1)
        self.docs[job["session_id"]] = html
        job["status"] = "completed"
        job["progress"] = 100
        if not job["billed"]:
            job["billed"] = True
            self.ops_charged += 1

    def export(self, session_id: str, fmt: str = "html") -> str:
        self.calls.append(("export", session_id))  # free
        html = self.docs.get(session_id, "")
        if fmt in {"markdown", "txt"}:
            import re
            return re.sub(r"<[^>]+>", "", html)
        # Exports strip chunk ids, exactly as the real server does.
        import re
        return re.sub(r'\s*data-chunk-id="[^"]*"', "", html)

    def session_html(self, session_id: str) -> str:
        return self.docs.get(session_id, "")
