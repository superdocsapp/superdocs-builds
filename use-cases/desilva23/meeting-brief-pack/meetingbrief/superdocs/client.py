"""A small, honest client for the SuperDocs API.

Four calls carry the whole contract — upload, chat, approve, export — and this
module implements those first. Everything else is depth added only where the
meeting-brief build actually needs it.

Three things here exist because the task document warned about them, and each
is the kind of thing you only find out by reading carefully or by losing a day:

**Proposed changes arrive double-encoded.** The content of a pending change is a
JSON *string* inside an already-parsed JSON object, so it needs a second parse.
The docs name this as the single most common reason integrators see diff cards
where every field reads `undefined`. `parse_pending_changes` does that parse in
one place, and says so loudly when it fails, rather than letting `undefined`
propagate into a UI.

**Slow is not broken.** Operations on large documents can take from thirty
seconds to several minutes with no visible progress. The polling here therefore
has a long ceiling and reports elapsed time as it waits, because a client that
gives up at thirty seconds turns a working system into a broken one.

**Operations cost money, so they are counted.** Every billable call is recorded
with what it was for. `Budget` stops the run before a call that would exceed the
ceiling rather than after — a stopping rule that triggers on the way out is an
autopsy, not a budget.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app/v1")

# The docs are explicit that a single edit can take minutes. The read timeout
# has to accommodate the slowest legitimate call, not the median one.
READ_TIMEOUT = 300.0
CONNECT_TIMEOUT = 15.0


class SuperDocsError(Exception):
    """A failure from the API, carrying whatever explanation it gave.

    The API returns structured errors that name the cause — a format that is not
    accepted, a limit that was crossed. Collapsing those into a status code
    would throw away the part that tells you what to do next.
    """

    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class BudgetExhausted(SuperDocsError):
    """The run stopped because the next call would have exceeded its ceiling."""


@dataclass
class Budget:
    """A stopping rule, checked before spending rather than after.

    The task document asks for this on day one: anything that loops gets a
    small-sample mode and a stopping rule. `limit` is in billable operations,
    which is what SuperDocs actually charges for — exports and reads are free,
    document-modifying chat turns and searches are not.
    """

    limit: int = 25
    spent: int = 0
    ledger: list[dict] = field(default_factory=list)

    def check(self, what: str, cost: int = 1) -> None:
        if self.spent + cost > self.limit:
            raise BudgetExhausted(
                f"stopping before {what!r}: it would take this run to "
                f"{self.spent + cost} operations against a ceiling of {self.limit}. "
                f"Raise the ceiling deliberately if that is what you want."
            )

    def record(self, what: str, cost: int = 1) -> None:
        self.spent += cost
        self.ledger.append({"operation": what, "cost": cost, "running_total": self.spent})

    def report(self) -> str:
        lines = [f"{row['operation']:<38} {row['cost']:>2}  → {row['running_total']}"
                 for row in self.ledger]
        return "\n".join(lines) + f"\n{'total billable operations':<38} {self.spent:>2}"


@dataclass
class PendingChange:
    """One proposed edit, waiting for a human decision.

    `change_id` is what the approve endpoint wants. The API reference calls this
    field `chunk_id` in its description while the guide's worked examples use
    `change_id`; both are kept here so a caller is not caught by whichever the
    server happens to be enforcing today.
    """

    change_id: str
    chunk_id: str
    kind: str
    before: str
    after: str
    raw: dict

    @property
    def summary(self) -> str:
        after = " ".join(self.after.split())
        return after[:140] + ("…" if len(after) > 140 else "")


class SuperDocs:
    def __init__(self, api_key: str | None = None, *, budget: Budget | None = None):
        key = api_key or os.environ.get("SUPERDOCS_API_KEY")
        if not key:
            raise SuperDocsError(
                "No API key. Put SUPERDOCS_API_KEY in the environment or in a .env "
                "file beside this project — never in the code, and never in a commit."
            )
        self._key = key
        self.budget = budget or Budget()
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- plumbing ----------------------------------------------------------

    def _request(self, method: str, path: str, **kw) -> dict:
        try:
            response = self._http.request(method, path, **kw)
        except httpx.TimeoutException as exc:
            raise SuperDocsError(
                f"{method} {path} timed out after {READ_TIMEOUT:.0f}s. The docs note that "
                f"large edits can take minutes — if this was a big document, poll a job "
                f"with chat_async instead of blocking on a synchronous call."
            ) from exc

        if response.status_code >= 400:
            try:
                body = response.json()
                detail = body.get("detail") or body.get("message") or body
            except Exception:
                body, detail = response.text, response.text
            raise SuperDocsError(
                f"{method} {path} failed: {detail}", status=response.status_code, body=body
            )

        return response.json() if response.content else {}

    # -- account -----------------------------------------------------------

    def whoami(self) -> dict:
        """Account and quota. Free — reads never cost operations."""
        return self._request("GET", "/agents/whoami")

    def promotions(self) -> dict:
        """Promotional credits.

        Deliberately separate from `whoami`, because the quota block in whoami
        does not account for promotions — an agent budgeting from whoami alone
        will believe it has far fewer operations than it does. Reported as a
        bug; until it changes, a caller that wants the true balance has to ask
        twice, so this client makes both easy.
        """
        return self._request("GET", "/promotions")

    # -- 1. upload ---------------------------------------------------------

    def upload_document(self, path: Path, session_id: str) -> dict:
        """Load a file as the *active, editable* document. Synchronous."""
        with path.open("rb") as fh:
            return self._request(
                "POST",
                "/documents/upload",
                files={"file": (path.name, fh)},
                data={"session_id": session_id},
            )

    def upload_attachment(self, path: Path, session_id: str, *, wait: bool = True) -> dict:
        """Load a file as *reference material* the AI can read but not edit.

        The distinction matters for this build: a meeting brief is assembled
        *from* an invitation and prior threads, and those sources must not be
        editable by the run that reads them. Attachments are the right shape —
        read-only context — and the brief itself is the active document.
        """
        with path.open("rb") as fh:
            job = self._request(
                "POST",
                "/attachments/upload",
                files={"file": (path.name, fh)},
                data={"session_id": session_id},
            )
        if wait and job.get("job_id"):
            self.wait_for_job(job["job_id"], what=f"attachment {path.name}")
        return job

    # -- 2. chat -----------------------------------------------------------

    def chat(
        self,
        message: str,
        session_id: str,
        *,
        document_html: str | None = None,
        model_tier: Literal["core", "turbo", "pro", "max"] = "core",
        response_mode: str | None = None,
    ) -> dict:
        """A synchronous edit turn. Billable when it modifies the document."""
        self.budget.check(f"chat: {message[:40]}")
        payload: dict[str, Any] = {"message": message, "session_id": session_id}
        if document_html is not None:
            payload["document_html"] = document_html
        if model_tier:
            payload["model_tier"] = model_tier
        if response_mode:
            payload["response_mode"] = response_mode

        result = self._request("POST", "/chat", json=payload)
        self.budget.record(f"chat: {message[:40]}")
        return result

    def chat_async(
        self,
        message: str,
        session_id: str,
        *,
        document_html: str | None = None,
        approval_mode: str | None = None,
        model_tier: str = "core",
        response_mode: str | None = None,
    ) -> str:
        """Start an edit as a job and return its id.

        This is the path that supports a human gate: with
        `approval_mode='ask_every_time'` the job pauses at `awaiting_approval`
        and will not touch the document until each proposed change is decided.
        The synchronous `chat` has no such pause, which is why the assembled
        brief is built through jobs even though it is slower.
        """
        self.budget.check(f"chat_async: {message[:40]}")
        payload: dict[str, Any] = {"message": message, "session_id": session_id}
        if document_html is not None:
            payload["document_html"] = document_html
        if approval_mode:
            payload["approval_mode"] = approval_mode
        if model_tier:
            payload["model_tier"] = model_tier
        if response_mode:
            payload["response_mode"] = response_mode

        job = self._request("POST", "/chat/async", json=payload)
        self.budget.record(f"chat_async: {message[:40]}")
        return job["job_id"]

    def get_job(self, job_id: str) -> dict:
        """Job state. Free."""
        return self._request("GET", f"/jobs/{job_id}")

    def wait_for_job(
        self,
        job_id: str,
        *,
        what: str = "job",
        until: tuple[str, ...] = ("completed", "failed", "cancelled", "awaiting_approval"),
        timeout: float = 900.0,
        on_tick=None,
    ) -> dict:
        """Poll until the job reaches a state worth acting on.

        The ceiling is fifteen minutes because the documentation says operations
        on large documents can take several minutes with no visible progress,
        and the correct read of a long silence is *still processing*. A client
        that gives up early reports a working system as broken.
        """
        started = time.monotonic()
        delay = 1.0

        while True:
            job = self.get_job(job_id)
            status = job.get("status")

            if status in until:
                return job

            elapsed = time.monotonic() - started
            if elapsed > timeout:
                raise SuperDocsError(
                    f"{what} was still {status!r} after {elapsed:.0f}s. That is beyond "
                    f"what the documentation describes as normal, so it is being "
                    f"reported rather than waited on further. Job id: {job_id}"
                )

            if on_tick:
                on_tick(status, elapsed)

            time.sleep(delay)
            delay = min(delay * 1.4, 8.0)  # back off, but stay responsive

    def wait_for_changes(
        self,
        job_id: str,
        *,
        settle_polls: int = 3,
        interval: float = 1.5,
        timeout: float = 900.0,
    ) -> dict:
        """Wait until a paused job has finished enumerating its proposed changes.

        `awaiting_approval` is **not** the moment the change list is complete.
        The job flips to that status as soon as the first change is ready and
        then keeps adding — its own event stream says "Processing 4 sections in
        parallel" *after* the status has already changed. A client that reads
        `pending_changes` on first sight of `awaiting_approval` therefore gets
        whatever happens to exist at that instant: five changes on one run and
        none on the next, from identical inputs.

        That failure is quiet and it is the worst kind for this build, because
        an empty change list looks exactly like "the AI decided nothing needed
        changing" — a human would approve nothing and never know a brief had
        been silently dropped.

        So this waits for the count to stop growing rather than for the status
        to change: stable across `settle_polls` consecutive reads, with the job
        still paused.
        """
        started = time.monotonic()
        last_count = -1
        stable = 0

        while True:
            job = self.get_job(job_id)
            status = job.get("status")
            count = len((job.get("metadata") or {}).get("pending_changes") or [])

            if status not in ("awaiting_approval", "in_progress", "pending"):
                return job  # completed, failed or cancelled — nothing to settle

            if status == "awaiting_approval":
                stable = stable + 1 if count == last_count and count > 0 else 0
                last_count = count
                if stable >= settle_polls:
                    return job

            if time.monotonic() - started > timeout:
                raise SuperDocsError(
                    f"job {job_id} was still enumerating changes after "
                    f"{timeout:.0f}s (last count {last_count})."
                )

            time.sleep(interval)

    # -- 3. approve --------------------------------------------------------

    @staticmethod
    def parse_pending_changes(job: dict) -> list[PendingChange]:
        """Read the proposed changes out of a paused job.

        **The second parse.** Each pending change carries its content as a
        JSON-encoded *string* inside the already-decoded job body. Skipping that
        parse is, per the documentation, the single most common integration
        failure: every field reads `undefined` and the diff card renders empty.

        This does the parse in exactly one place and raises loudly if the shape
        is not what it expects, because a silent `{}` here becomes an approval
        screen showing a human nothing at all — and a human approving nothing is
        worse than no gate.
        """
        metadata = job.get("metadata") or {}
        raw_changes = metadata.get("pending_changes") or []

        changes: list[PendingChange] = []
        for index, raw in enumerate(raw_changes):
            content = raw.get("content", raw)

            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise SuperDocsError(
                        f"pending change {index} carried a string that is not JSON. "
                        f"This is the field the docs say needs a second parse; if the "
                        f"encoding has changed, this is the place to fix it. "
                        f"First 200 characters: {content[:200]!r}"
                    ) from exc

            if not isinstance(content, dict):
                raise SuperDocsError(
                    f"pending change {index} decoded to {type(content).__name__}, "
                    f"not an object. Refusing to show a reviewer a change this code "
                    f"cannot describe."
                )

            changes.append(
                PendingChange(
                    change_id=str(
                        raw.get("change_id")
                        or content.get("change_id")
                        or raw.get("chunk_id")
                        or content.get("chunk_id")
                        or index
                    ),
                    chunk_id=str(raw.get("chunk_id") or content.get("chunk_id") or index),
                    kind=str(content.get("type") or content.get("kind") or "edit"),
                    before=str(content.get("before") or content.get("old_html") or ""),
                    after=str(content.get("after") or content.get("new_html")
                              or content.get("html") or ""),
                    raw=raw,
                )
            )
        return changes

    def approve(
        self,
        session_id: str,
        job_id: str,
        *,
        change_id: str | None = None,
        approved: bool = True,
        feedback: str | None = None,
        changes: list[dict] | None = None,
    ) -> dict:
        """Decide on proposed changes. Free — a decision is not an operation.

        `job_id` is required, which is worth stating because the API reference
        for this endpoint does not mention it: its description names only
        `approved`, `feedback` and a `changes` array. Only the guide's worked
        examples show `job_id` and `change_id`. Sending what the reference
        describes returns a 422 naming the missing field.

        Either one change (`change_id` + `approved`) or a batch (`changes`),
        which is a list of per-item decisions. There is deliberately no
        "approve everything" helper: the batch form still names every change
        individually, so approving twelve edits is twelve recorded decisions
        rather than one blanket act.
        """
        payload: dict[str, Any] = {"job_id": job_id}
        if changes is not None:
            payload["changes"] = changes
            payload["approved"] = approved
        else:
            payload["approved"] = approved
            if change_id is not None:
                payload["change_id"] = change_id
        if feedback:
            payload["feedback"] = feedback

        return self._request("POST", f"/chat/{session_id}/approve", json=payload)

    # -- 4. export ---------------------------------------------------------

    def export(
        self,
        *,
        session_id: str | None = None,
        html: str | None = None,
        fmt: Literal["docx", "pdf", "html", "markdown", "txt"] = "docx",
        out_path: Path | None = None,
    ) -> bytes | Path:
        """Export the document. Free — exports never cost operations."""
        if not session_id and not html:
            raise SuperDocsError("export needs either a session_id or html to render")

        payload: dict[str, Any] = {"format": fmt}
        if session_id:
            payload["session_id"] = session_id
        if html:
            payload["html"] = html

        response = self._http.post("/documents/export", json=payload)
        if response.status_code >= 400:
            raise SuperDocsError(
                f"export failed: {response.text[:300]}", status=response.status_code
            )

        # The endpoint may hand back the bytes, or a URL to fetch them from.
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            body = response.json()
            url = body.get("download_url") or body.get("url")
            if not url:
                raise SuperDocsError(f"export returned JSON with no download url: {body}")
            data = httpx.get(url, timeout=READ_TIMEOUT, follow_redirects=True).content
        else:
            data = response.content

        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            return out_path
        return data

    # -- reading, all free -------------------------------------------------

    def document_structure(self, document_id: str) -> dict:
        """Headings and section counts, explicitly non-billable.

        The cheap way to answer "did my edit land?" — the docs are emphatic that
        you should never export a whole document just to check its structure.
        """
        return self._request("GET", f"/documents/{document_id}")

    def list_documents(self) -> dict:
        return self._request("GET", "/documents")


def load_env(path: Path | None = None) -> None:
    """Read a .env beside the project, without a dependency.

    Values are put into the environment and never logged. The key lives in a
    file that is gitignored, which is the whole of the secret handling here:
    never in code, never in a commit, never in a screenshot.
    """
    env = path or Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip())
