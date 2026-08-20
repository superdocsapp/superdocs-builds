"""Fixtures. Nothing here touches the network or wants an API key.

The SuperDocs client is exercised against a fake **transport**, not a mocked
client, so the tests cover the request shapes, the double parse of proposed
changes, the error mapping and the budget — the parts most likely to be wrong
— rather than confirming that a mock returns what the mock was told to return.

The fake also *applies* the edits it is asked for, to its own stored copy of
the document. That is the part that makes the verification tests mean
anything. A fake that accepts an instruction and changes nothing would make
every "did the edit land" assertion pass by default, and would make the
verification code look correct while it did nothing at all. Task 2 of this
round shipped exactly that mistake for a day.

What the fake deliberately does **not** model is judgement. It is a
cooperative service: told to change the value in "the sentence that states the
retry backoff", it changes the next one it finds. Whether a real model
disambiguates correctly is a live question, and it is answered by the live run
in the README rather than by a fixture that was written to agree with me.
"""

from __future__ import annotations

import html as html_module
import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from docsync.superdocs import Ledger, SuperDocs

EXAMPLE = Path(__file__).resolve().parent.parent / "example"

WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 15: "fifteen", 20: "twenty", 30: "thirty",
    45: "forty-five", 60: "sixty",
}


def word_form(text: str) -> str | None:
    try:
        return WORDS.get(int(text.strip()))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Repositories on disk
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway copy of the example service."""
    root = tmp_path / "svc"
    shutil.copytree(EXAMPLE, root)
    return root


@pytest.fixture
def git_repo(repo: Path) -> Path:
    """The same, committed to a real git repository.

    A real repository rather than a stub of one: the whole point of ``--base``
    is that it shells out to ``git show``, and a mock of git would test the
    mock. It needs git on PATH, which is a fair thing for a tool that reads git
    revisions to require.
    """
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "docsync tests")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout


@pytest.fixture
def git(): # noqa: D401
    """Run a git command inside a repository, for tests that need a second commit."""
    return _git


def edit_file(root: Path, relpath: str, old: str, new: str) -> None:
    path = root / relpath
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not found in {relpath}"
    path.write_text(text.replace(old, new), encoding="utf-8")


# ---------------------------------------------------------------------------
# The fake service
# ---------------------------------------------------------------------------


class FakeSuperDocs:
    """Stands in for the API, behaving the way it is documented to behave.

    Including the awkward parts: multipart upload adds a document and returns
    the roster, an ``ask_every_time`` job pauses before completing, and the
    proposed changes can arrive JSON-encoded inside a JSON field.
    """

    _REPLACE_ALL = re.compile(
        r'states the .+? as "([^"]+)", once\. Replace that one occurrence with "([^"]+)"', re.S
    )
    _REPLACE_ONE = re.compile(
        r'set the value to "([^"]+)"\. It currently reads "([^"]+)"', re.S
    )
    _PROSE = re.compile(r'It is now "([^"]+)" \(it was "([^"]+)"\)', re.S)
    _ADD = re.compile(r"Add an entry for each of: ([^.]+)\.", re.S)
    _REMOVE = re.compile(r"Remove the entry for each of: ([^.]+)\.", re.S)

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.documents: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.approvals: list[dict] = []
        self.pending_ops: dict[str, tuple[str, list]] = {}
        self._seq = 0
        # Test knobs.
        self.encode_pending_as_string = False
        self.drop_values: set[str] = set()
        self.fail_next_edit = False
        self.export_status = 200
        # When set, the next edit pauses as a *continue prompt* rather than as
        # a change review. Both share the status `awaiting_approval`, and
        # calling /approve on the wrong one returns a bare 409, so a caller
        # that does not branch on metadata.awaiting_kind breaks here.
        self.continue_prompt_next = False
        self.completes_without_pausing = False
        # Bypasses the gate on the FIRST send only, then behaves. Models the
        # intermittent live failure that the single bounded retry recovers from.
        self.completes_without_pausing_once = False
        # Models a service that over-applies: told to change one occurrence, it
        # changes every one. Not hypothetical — a live run did exactly this to
        # a runbook and rewrote a timeout that was never meant to move.
        self.overreach = False

    # -- transport ---------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body: dict = {}
        if request.content and request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            try:
                body = json.loads(request.content)
            except json.JSONDecodeError:
                body = {}
        self.requests.append((request.method, path, body))

        if path.endswith("/documents/upload"):
            return self._upload(request)
        if path.endswith("/chat/async"):
            return self._chat_async(body)
        if "/approve" in path:
            job = self.jobs.get(body.get("job_id"), {})
            if (job.get("metadata") or {}).get("awaiting_kind") == "continue_prompt":
                # The real service rejects /approve on a continue prompt with a
                # bare 409. Checked before the happy path so a caller that does
                # not branch on awaiting_kind fails here rather than passing.
                return httpx.Response(409, json={"detail": "this job is awaiting a continue"})
            self.approvals.append(body)
            if job:
                job["status"] = "completed"
            self._apply_approved(body)
            return httpx.Response(200, json={"status": "resumed"})
        if "/continue" in path:
            job = self.jobs[body["job_id"]]
            job["status"] = "awaiting_approval"
            job["metadata"]["awaiting_kind"] = "approval"
            return httpx.Response(200, json={"status": "resumed"})
        if path.startswith("/v1/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=self.jobs.get(job_id, {"status": "completed"}))
        if path.endswith("/documents/export"):
            if self.export_status != 200:
                return httpx.Response(self.export_status, json={"detail": "export failed"})
            return httpx.Response(200, content=to_markdown(body.get("html") or "").encode())
        if "/sessions/" in path and path.endswith("/documents") and request.method == "GET":
            return self._roster(path, request)
        if path.endswith("/agents/whoami"):
            return httpx.Response(
                200, json={"subscription_tier": "pro", "monthly_used": 3, "monthly_limit": 10000}
            )
        return httpx.Response(200, json={})

    def _upload(self, request: httpx.Request) -> httpx.Response:
        raw = request.content.decode("utf-8", errors="replace")
        fields = dict(re.findall(r'name="([^"]+)"\r\n\r\n([^\r]*)\r\n', raw))
        match = re.search(r'filename="([^"]+)"', raw)
        filename = match.group(1) if match else "unknown.md"
        session = fields.get("session_id", "unknown")
        open_mode = fields.get("open_mode", "replace")

        in_session = [d for d, meta in self.documents.items() if meta["session"] == session]
        if open_mode in ("new_focused", "new_tab", "background") or not in_session:
            doc_id = f"doc_{len(self.documents) + 1:02d}"
        else:
            # What upload-base64 does, and what the multipart endpoint does when
            # open_mode is not one of the "add" modes: replace the focused one.
            doc_id = in_session[-1]

        self.documents[doc_id] = {
            "session": session,
            "title": filename.removesuffix(".md"),
            "raw": _multipart_file_body(raw),
        }
        return httpx.Response(
            200,
            json={
                "session_id": session,
                "document_id": doc_id,
                "filename": filename,
                "chunks_count": 12,
                "version_id": "ver_stub",
                # An upload response's roster entries carry `title: None`; the
                # title only appears when the roster is read back. Verified in
                # production during Task 2, and getting it wrong is what
                # produced a manifest full of nulls.
                "documents": [
                    {"document_id": did, "title": None, "focused": did == doc_id,
                     "chunks_count": 12}
                    for did, meta in self.documents.items()
                    if meta["session"] == session
                ],
            },
        )

    def _roster(self, path: str, request: httpx.Request) -> httpx.Response:
        session = path.split("/sessions/")[1].split("/")[0]
        include_html = "include_html=true" in (request.url.query or b"").decode()
        mine = {d: m for d, m in self.documents.items() if m["session"] == session}
        focused = list(mine)[-1] if mine else None
        return httpx.Response(
            200,
            json={
                "session_id": session,
                "focused_document_id": focused,
                "documents": [
                    {
                        "document_id": did,
                        "title": meta["title"],
                        "focused": did == focused,
                        "chunks_count": 12,
                        "html": to_html(meta["raw"]) if include_html else None,
                    }
                    for did, meta in mine.items()
                ],
            },
        )

    # -- editing -----------------------------------------------------------

    def _operations(self, instruction: str) -> list[tuple]:
        """The edits an instruction asks for, in the order it asks for them."""
        ops: list[tuple] = []
        for before, after in self._REPLACE_ALL.findall(instruction):
            ops.append(("all", before, after))
        for after, before in self._REPLACE_ONE.findall(instruction):
            ops.append(("one", before, after))
        for after, before in self._PROSE.findall(instruction):
            ops.append(("prose", before, after))
        for block in self._ADD.findall(instruction):
            for item in re.findall(r'"([^"]+)"', block):
                ops.append(("add", "", item))
        for block in self._REMOVE.findall(instruction):
            for item in re.findall(r'"([^"]+)"', block):
                ops.append(("remove", item, ""))
        return ops

    def _active_job_in(self, session: str) -> str | None:
        """A session runs one job at a time, and a paused one still counts.

        Modelled because the real API enforces it and the first version of this
        fake did not, which is how a design that could never work in production
        passed a full offline suite. A job left at ``awaiting_approval`` — which
        is exactly where the human gate parks every job — keeps the session
        busy until it is approved or rejected.
        """
        for job_id, job in self.jobs.items():
            if job.get("session") != session:
                continue
            if job.get("status") in ("pending", "in_progress", "awaiting_approval"):
                return job_id
        return None

    def _chat_async(self, body: dict) -> httpx.Response:
        session = body.get("session_id", "")
        busy = self._active_job_in(session)
        if busy:
            return httpx.Response(
                409,
                json={
                    "error_code": "session_busy",
                    "message": "The AI is still working on a previous request in this "
                    "conversation. Wait for it to finish or stop it, then send your "
                    "message again.",
                    "suggested_action": "Poll get_job/list_jobs for the active job, cancel "
                    "it, or use a different session_id.",
                    "active_jobs": 1,
                },
            )
        self._seq += 1
        job_id = f"job_{self._seq}"
        if self.fail_next_edit:
            self.fail_next_edit = False
            self.jobs[job_id] = {
                "status": "failed", "error": "the model gave up", "session": session
            }
            return httpx.Response(200, json={"job_id": job_id})

        doc_id = body.get("document_id") or (list(self.documents)[-1] if self.documents else None)
        proposed, applied_ops = [], []
        for i, op in enumerate(self._operations(body.get("message", "")), start=1):
            kind, before, after = op
            if after and after in self.drop_values:
                continue  # a field the model quietly skipped
            change_id = f"{job_id}_c{i}"
            proposed.append(
                {
                    "change_id": change_id,
                    "operation": {"add": "insert", "remove": "delete"}.get(kind, "edit"),
                    "chunk_id": f"chunk-{i}",
                    "old_html": f"<p>{html_module.escape(before)}</p>" if before else "",
                    "new_html": f"<p>{html_module.escape(after)}</p>" if after else "",
                    "ai_explanation": f"{kind}: {before or '—'} → {after or '—'}",
                }
            )
            applied_ops.append((change_id, op))

        self.pending_ops[job_id] = (doc_id, applied_ops)
        metadata: dict = {"awaiting_kind": "approval"}
        if self.continue_prompt_next:
            self.continue_prompt_next = False
            metadata["awaiting_kind"] = "continue_prompt"
        metadata["pending_changes"] = (
            json.dumps(proposed) if self.encode_pending_as_string else proposed
        )
        status = "awaiting_approval" if proposed else "completed"
        if self.completes_without_pausing:
            status = "completed"
        if self.completes_without_pausing_once:
            self.completes_without_pausing_once = False
            status = "completed"
        self.jobs[job_id] = {"status": status, "metadata": metadata, "session": session}
        return httpx.Response(200, json={"job_id": job_id})

    def _apply_approved(self, body: dict) -> None:
        doc_id, ops = self.pending_ops.get(body.get("job_id"), (None, []))
        if not doc_id or doc_id not in self.documents:
            return
        approved = {
            d.get("change_id")
            for d in (body.get("changes") or [])
            if d.get("approved", body.get("approved"))
        }
        raw = self.documents[doc_id]["raw"]
        for change_id, (kind, before, after) in ops:
            if change_id not in approved:
                continue
            if self.overreach and kind == "one":
                kind = "all"
            raw = _apply_one(raw, kind, before, after)
        self.documents[doc_id]["raw"] = raw

    def body_of(self, doc_id: str) -> str:
        return self.documents[doc_id]["raw"]

    def find_document(self, name_fragment: str) -> str:
        for doc_id, meta in self.documents.items():
            if name_fragment in meta["title"]:
                return doc_id
        raise AssertionError(f"no uploaded document matching {name_fragment!r}")


def _replace_tokens(raw: str, before: str, after: str, count: int = 0) -> str:
    """Substitute respecting token boundaries, the way a reader would.

    The first version used a bare ``str.replace``, which turned ``30 seconds``
    into ``50 seconds`` when asked to change a ``3``. That is not what a
    competent editor does, so modelling it made the fake fail edits the real
    service handles. It is still worth knowing the difference exists — the
    instruction now names the single occurrence rather than asking for all of
    them, precisely because a blanket instruction invites the naive reading.
    """
    pattern = r"(?<![\w/-])(?<!\d\.)" + re.escape(before) + r"(?![\w/-])(?!\.\d)"
    return re.sub(pattern, after.replace("\\", "\\\\"), raw, count=count)


def _apply_one(raw: str, kind: str, before: str, after: str) -> str:
    if kind == "all":
        return _replace_tokens(raw, before, after)
    if kind == "one":
        return _replace_tokens(raw, before, after, count=1)
    if kind == "prose":
        old_word, new_word = word_form(before), word_form(after)
        if old_word and new_word:
            return raw.replace(old_word, new_word)
        return raw  # a prose edit the fake cannot express
    if kind == "add":
        return raw.rstrip("\n") + f"\n| `{after}` | added by docsync. |\n"
    if kind == "remove":
        return "\n".join(line for line in raw.splitlines() if before not in line) + "\n"
    return raw


def _multipart_file_body(raw: str) -> str:
    """The file part of a multipart body, and only the file part.

    Splitting on the second blank line lands in the ``session_id`` field rather
    than the document, which stores the wrong text and makes every later
    assertion meaningless.
    """
    marker = 'name="file"'
    start = raw.find(marker)
    if start < 0:
        return ""
    body_start = raw.find("\r\n\r\n", start)
    if body_start < 0:
        return ""
    body_start += 4
    end = raw.find("\r\n--", body_start)
    return raw[body_start : end if end > 0 else len(raw)]


def to_html(raw: str) -> str:
    """Markdown-ish text as the HTML the service would hold.

    Escaped and wrapped rather than returned as-is, so that ``apply.to_text``
    is exercised for real on every verification rather than being handed
    something that was already plain text.
    """
    paragraphs = html_module.escape(raw).split("\n\n")
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)


def to_markdown(html: str) -> str:
    from docsync.apply import to_text

    return to_text(html)


# ---------------------------------------------------------------------------


@pytest.fixture
def fake() -> FakeSuperDocs:
    return FakeSuperDocs()


@pytest.fixture
def client(fake: FakeSuperDocs) -> SuperDocs:
    transport = httpx.MockTransport(fake.handler)
    # Mirrors the production client: no client-level Content-Type, so a
    # multipart upload can set its own boundary. Pinning it here is what would
    # make the fixture accept a request shape the real client cannot send.
    http = httpx.Client(
        transport=transport,
        base_url="https://api.superdocs.app",
        headers={"Authorization": "Bearer sk_test"},
    )
    return SuperDocs("sk_test_key", ledger=Ledger(limit=100), client=http)
