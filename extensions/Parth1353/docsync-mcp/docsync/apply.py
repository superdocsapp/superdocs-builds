"""Applying a plan, in two phases with a person in between.

The split is the point. ``stage`` sends the edits and stops at the gate;
``commit`` applies exactly the changes somebody said yes to. Between them the
run can end, the process can exit, and the human can go to lunch — the paused
jobs live server-side and the batch that describes them lives in
``.docsync/pending.json``.

That shape exists because of where this runs. A CLI can block on ``input()``
and call it a human gate. An MCP server cannot: the agent calls a tool, the
tool returns, and a person looks at the result in their editor whenever they
look at it. A gate that only works when a terminal is attached is not a gate,
it is a prompt. So the same two calls back both, and the CLI's interactive mode
is just ``stage`` → ask → ``commit`` in one process.

What ``commit`` will not do:

* approve anything that was not named. There is no "approve everything" path
  through this module; ``--yes`` builds a reviewer that returns ``True``, and
  the CLI says so out loud when it does.
* claim a prose edit landed. Only anchored changes are verified, because only
  they have a value to search for. Everything else is reported as *applied,
  not verified*, which is the truth.
* write a document back over uncommitted work, or write back a document whose
  verification failed.
"""

from __future__ import annotations

import html as html_module
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from docsync.facts import is_dirty, is_git_repo
from docsync.plan import ChangePlan, DocumentPlan, content_hash, occurrences, split_front_matter
from docsync.state import Pending, PendingChange, PendingJob, State
from docsync.superdocs import BudgetExceeded, SuperDocs, SuperDocsError

log = logging.getLogger(__name__)

Reviewer = Callable[[PendingChange, PendingJob], bool]
Progress = Callable[[str, str], None] | None

MAX_GATE_ROUNDS = 5


def session_for(prefix: str, path: str, workspace_id: str = "") -> str:
    """One SuperDocs session per document, and this is not a style preference.

    A session runs one job at a time. A job parked at ``awaiting_approval`` is
    still an active job, so with every document in one session the second
    ``chat/async`` comes back ``409 session_busy`` — *"The AI is still working
    on a previous request in this conversation"* — and stays that way until
    somebody approves the first one.

    That is fatal to the whole point of this design. Staging every document and
    then holding all the diffs for one review is the reason the gate works in
    an editor, where nobody is sitting at a blocking prompt. In one session it
    is not merely slower, it is impossible.

    Found on the first live run and not before it: every offline test passed,
    because a fake with no concept of session occupancy has no way to say no.
    The API's own error names the fix, which is what made it a ten-minute
    problem instead of an afternoon.

    The id is derived from the path so it is stable across runs — the same
    document lands in the same session and keeps its document id, and a re-run
    costs an upload rather than a new session's worth of confusion.

    ``workspace_id`` is what stops two *different* checkouts colliding. Without
    it the id is a pure function of the registry's ``session:`` value and the
    document path, so a second clone of the same repository — or an abandoned
    run whose jobs are still parked at the gate — owns the same sessions and
    every edit comes back ``409 session_busy``. That happened while testing
    this: a run killed by a timeout left three jobs waiting for approval, and
    the next run in a fresh directory could not send anything at all.

    The id is generated once per workspace and recorded in ``state.json``, so a
    colleague who has the state file reuses the same sessions and pays no extra
    uploads, while a fresh checkout gets its own.
    """
    import hashlib

    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")[:48]
    digest = hashlib.sha1(f"{workspace_id}:{path}".encode()).hexdigest()[:8]
    return f"{prefix}-{slug}-{digest}"


# ---------------------------------------------------------------------------
# Phase one — send, and stop at the gate
# ---------------------------------------------------------------------------


def stage(
    client: SuperDocs,
    plan: ChangePlan,
    state: State,
    *,
    session_prefix: str,
    model_tier: str = "pro",
    poll_timeout: float = 420.0,
    on_progress: Progress = None,
) -> Pending:
    """Upload what needs uploading, send one instruction per document, pause.

    Nothing is approved here and nothing is written to disk here. The return
    value is the set of proposed changes waiting for a decision.
    """
    if not state.workspace_id:
        state.save()  # mints the workspace id before any session is derived
    pending = Pending(root=plan.registry_root, session_id=session_prefix)

    def note(who: str, message: str) -> None:
        if on_progress:
            on_progress(who, message)

    for doc in plan.documents:
        if not doc.this_round:
            continue
        try:
            job = _stage_one(
                client,
                doc,
                state,
                session_prefix=session_prefix,
                model_tier=model_tier,
                poll_timeout=poll_timeout,
                note=note,
            )
        except BudgetExceeded:
            # Caught before the general handler, and re-raised rather than
            # recorded. BudgetExceeded is a SuperDocsError, so without this the
            # per-document rescue below swallows it and the run carries on
            # trying every remaining document — turning the one hard stopping
            # rule in the tool into a per-document warning. What has already
            # been staged is saved first, so the operations that were spent are
            # not thrown away with it.
            pending.save()
            state.save()
            raise
        except SuperDocsError as exc:
            # One document failing must not abandon the rest. A partial batch
            # that names what did and did not go out is recoverable; a run that
            # dies halfway and says nothing is not.
            log.error("staging failed on %s: %s", doc.path, exc)
            job = PendingJob(
                path=doc.path,
                title=doc.title,
                document_id=state.documents[doc.path].document_id
                if doc.path in state.documents
                else "",
                job_id="",
                session_id=session_for(session_prefix, doc.path, state.workspace_id),
                instruction=doc.instruction,
                front_matter="",
                error=str(exc),
            )
        pending.jobs.append(job)

    pending.save()
    state.save()
    return pending


def _stage_one(
    client: SuperDocs,
    doc: DocumentPlan,
    state: State,
    *,
    session_prefix: str,
    model_tier: str,
    poll_timeout: float,
    note: Callable[[str, str], None],
) -> PendingJob:
    record = state.documents.get(doc.path)
    session_id = (record.session_id if record and record.session_id
                  else session_for(session_prefix, doc.path, state.workspace_id))
    path = Path(state.root) / doc.path
    text = path.read_text(encoding="utf-8")
    front, body = split_front_matter(text)

    document_id = state.documents[doc.path].document_id if doc.path in state.documents else ""
    if doc.needs_upload or not document_id:
        note(doc.path, "uploading")
        document_id = _upload(client, doc, body, session_id=session_id)
        state.record_upload(
            doc.path, document_id, content_hash(text), doc.title, session_id=session_id
        )

    # One bounded retry, for a gate that sometimes does not engage.
    #
    # Measured live: with ``approval_mode=ask_every_time`` a job occasionally
    # runs to ``completed`` without ever pausing, replies "✅ I've completed
    # the requested change", returns a ``document_changes.updated_html`` — and
    # persists nothing. The document is untouched and no change was ever
    # offered for review. Observed twice in about eighteen sends of the same
    # document, and not reproducible on demand: six identical repeats of the
    # exact instruction that triggered it all paused correctly.
    #
    # Since it is not a phrasing problem it cannot be prompted away, only
    # detected and retried. Exactly one retry: if the gate will not engage
    # twice, that is a finding for a person rather than a loop to spin in, and
    # the run says so.
    attempts = 0
    while True:
        attempts += 1
        note(doc.path, "sending the edit" if attempts == 1 else "re-sending (the gate did not engage)")
        job_id = client.chat_async(
            doc.instruction,
            session_id=session_id,
            document_id=document_id,
            approval_mode="ask_every_time",
            model_tier=model_tier,
        )
        job = client.wait_for_job(
            job_id, timeout=poll_timeout, on_tick=lambda status, _job: note(doc.path, str(status))
        )

        # A large edit can pause to ask whether to keep going. That is not a
        # change review and calling /approve on it returns 409, so it is
        # resolved here rather than handed to a person as if it were a diff.
        rounds = 0
        while job.get("status") == "awaiting_approval" and rounds < MAX_GATE_ROUNDS:
            if client.awaiting_kind(job) != "continue_prompt":
                break
            rounds += 1
            note(doc.path, "large edit paused; continuing")
            client.continue_chat(session_id, job_id, keep_going=True)
            job = client.wait_for_job(job_id, timeout=poll_timeout)

        if job.get("status") == "awaiting_approval" or job.get("status") == "failed":
            break
        if attempts >= 2:
            break

    verifiable, unverifiable = _checks_for(doc)
    staged = PendingJob(
        path=doc.path,
        title=doc.title,
        document_id=document_id,
        job_id=job_id,
        session_id=session_id,
        instruction=doc.instruction,
        front_matter=front,
        verifiable=verifiable,
        unverifiable=unverifiable,
        invariants=list(doc.invariants),
    )

    if job.get("status") == "failed":
        staged.error = str(job.get("error") or "the job failed without giving a reason")
        return staged
    if job.get("status") != "awaiting_approval":
        # Reported precisely, because the three causes need different actions
        # and the earlier wording ("nothing matched") named only one of them.
        # The service has been seen to reply that it completed the change while
        # persisting nothing at all, so "it said it worked" is not evidence.
        staged.error = (
            f"the job finished as {job.get('status')} without pausing for approval, "
            f"twice. Either nothing in this document matched the instruction, or the "
            f"service did not honour approval_mode=ask_every_time. Check the document "
            f"before assuming the edit landed — the reply can claim success while "
            f"nothing was persisted."
        )
        return staged

    for raw in client.pending_changes(job):
        staged.changes.append(
            PendingChange(
                change_id=str(raw.get("change_id") or ""),
                operation=str(raw.get("operation") or "edit"),
                old_text=to_text(raw.get("old_html")),
                new_text=to_text(raw.get("new_html")),
                explanation=str(raw.get("ai_explanation") or ""),
            )
        )
    if not staged.changes:
        staged.error = "the job paused but proposed no changes"
    note(doc.path, f"{len(staged.changes)} change(s) waiting for review")
    return staged


def _checks_for(doc: DocumentPlan) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The post-edit checks this document's changes can and cannot support.

    A check is *sound* here for a reason that is easy to miss: a change is only
    ever sent when its new value occurs **zero** times in the document. That is
    what ``classify`` established before anything was spent — a document that
    already contains the new value is marked ``current`` and never contacted.
    So finding the new value afterwards means the edit put it there, rather
    than meaning it happened to be somewhere in the file all along.

    List facts are verifiable in both directions: an added entry must now be
    present, and a removed one must now be absent. Prose edits are not
    verifiable in either, and are listed as such rather than assumed good.
    """
    verifiable: list[dict[str, str]] = []
    unverifiable: list[dict[str, str]] = []
    sendable_keys = {c.key for c in doc.sendable}

    for change in doc.this_round:
        if change.key not in sendable_keys:
            unverifiable.append(
                {
                    "key": change.key,
                    "label": change.label,
                    "before": change.before_display,
                    "after": change.after_display,
                    "mode": "prose",
                }
            )
            continue
        if change.is_list:
            for item in change.added:
                verifiable.append(
                    {"key": change.key, "label": change.label, "before": "",
                     "after": item, "mode": "present"}
                )
            for item in change.removed:
                verifiable.append(
                    {"key": change.key, "label": change.label, "before": item,
                     "after": item, "mode": "absent"}
                )
            continue
        verifiable.append(
            {
                "key": change.key,
                "label": change.label,
                "before": str(change.before_text),
                "after": str(change.after_text),
                "mode": "present",
            }
        )
    return verifiable, unverifiable


def _upload(client: SuperDocs, doc: DocumentPlan, body: str, *, session_id: str) -> str:
    """Upload and come back with an id that is certainly this document's.

    The filename is the repo-relative path flattened, so two ``README.md``
    files in different directories cannot collide in the session roster. The id
    from the upload response is cross-checked against the roster rather than
    trusted, because the roster is the only authoritative source of ids and
    the difference is invisible until an edit lands on the wrong document.
    """
    filename = doc.path.replace("/", "__")
    result = client.upload_markdown(filename=filename, text=body, session_id=session_id)
    if result.get("dry_run"):
        return "dry-run-document"

    claimed = result.get("document_id")
    roster = client.session_documents(session_id)
    ids = {d.get("document_id") for d in (roster.get("documents") or [])}
    if claimed and claimed in ids:
        return str(claimed)

    for entry in roster.get("documents") or []:
        title = str(entry.get("title") or "")
        if title in (filename, filename.removesuffix(".md")):
            return str(entry.get("document_id"))
    raise SuperDocsError(
        f"uploaded {doc.path} but could not find it in the session roster",
        fix="the upload returned no usable document id and no roster entry matched its "
        "filename; check GET /v1/sessions/{session_id}/documents",
    )


# ---------------------------------------------------------------------------
# Phase two — decide, verify, write back
# ---------------------------------------------------------------------------


@dataclass
class DocumentOutcome:
    path: str
    document_id: str = ""
    approved: int = 0
    rejected: int = 0
    verified: list[str] = field(default_factory=list)
    not_landed: list[str] = field(default_factory=list)
    collateral: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    written_back: bool = False
    write_back_skipped: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.not_landed and not self.collateral


@dataclass
class ApplyReport:
    outcomes: list[DocumentOutcome] = field(default_factory=list)
    ledger: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(outcome.ok for outcome in self.outcomes)

    @property
    def approved(self) -> int:
        return sum(o.approved for o in self.outcomes)

    @property
    def rejected(self) -> int:
        return sum(o.rejected for o in self.outcomes)


def commit(
    client: SuperDocs,
    pending: Pending,
    state: State,
    *,
    decisions: dict[str, bool],
    write_back: bool = True,
    force_write: bool = False,
    poll_timeout: float = 420.0,
    on_progress: Progress = None,
) -> ApplyReport:
    """Approve exactly what was decided, then check what actually landed.

    ``decisions`` maps change id → keep it. A change id that is not in the map
    is **rejected**, not approved: the default for an undecided change is no.
    """
    report = ApplyReport()

    def note(who: str, message: str) -> None:
        if on_progress:
            on_progress(who, message)

    for job in pending.jobs:
        outcome = DocumentOutcome(path=job.path, document_id=job.document_id)
        if job.error:
            outcome.error = job.error
            report.outcomes.append(outcome)
            continue

        verdicts = [
            {
                "change_id": change.change_id,
                "approved": bool(decisions.get(change.change_id, False)),
                **(
                    {}
                    if decisions.get(change.change_id, False)
                    else {"feedback": "Not approved by the reviewer."}
                ),
            }
            for change in job.changes
        ]
        outcome.approved = sum(1 for v in verdicts if v["approved"])
        outcome.rejected = len(verdicts) - outcome.approved

        try:
            note(job.path, f"approving {outcome.approved} of {len(verdicts)}")
            client.approve(
                job.session_id or pending.session_id,
                job.job_id,
                approved=True,  # required at the top level even for batch shapes
                changes=verdicts,
            )
            client.wait_for_job(job.job_id, timeout=poll_timeout)
        except SuperDocsError as exc:
            outcome.error = str(exc)
            report.outcomes.append(outcome)
            continue

        if outcome.approved == 0:
            outcome.write_back_skipped = "nothing was approved"
            report.outcomes.append(outcome)
            continue

        try:
            _verify_and_write(
                client,
                job,
                state,
                outcome,
                session_id=job.session_id or pending.session_id,
                write_back=write_back,
                force_write=force_write,
                note=note,
            )
        except SuperDocsError as exc:
            outcome.error = str(exc)
        report.outcomes.append(outcome)

    report.ledger = client.ledger.summary()
    state.save()
    return report


def _has_foreign_edits(state: State, relpath: str, target: Path) -> bool:
    """Does this file hold uncommitted work that docsync did not put there?

    The refusal to overwrite uncommitted changes exists to protect a person's
    half-written paragraph. It must not protect the file from *this tool's own*
    previous round, and the first version did exactly that: a document with two
    changed facts takes two rounds, round one wrote the file, and round two then
    saw an uncommitted change and refused — so the local file never advanced,
    the same edit was planned again, and the run burned two operations a round
    until it hit the round cap.

    The recorded content hash is what separates the two. If the file on disk is
    byte-identical to what docsync last wrote, the only uncommitted changes are
    ours and overwriting them is safe. Anything else is somebody's work.
    """
    root = Path(state.root)
    if not is_git_repo(root) or not is_dirty(root, relpath):
        return False
    record = state.documents.get(relpath)
    if record is None:
        return True
    try:
        return content_hash(target.read_text(encoding="utf-8")) != record.written_hash
    except (OSError, UnicodeDecodeError):
        return True


def _verify_and_write(
    client: SuperDocs,
    job: PendingJob,
    state: State,
    outcome: DocumentOutcome,
    *,
    session_id: str,
    write_back: bool,
    force_write: bool,
    note: Callable[[str, str], None],
) -> None:
    note(job.path, "reading the document back")
    roster = client.session_documents(session_id, include_html=True)
    document_html = client.document_html(roster, job.document_id)
    if document_html is None:
        outcome.error = (
            "the session roster returned no body for this document, so what landed "
            "cannot be checked"
        )
        return

    text = to_text(document_html)
    for item in job.verifiable:
        hits = occurrences(text, item["after"])
        landed = hits == 0 if item.get("mode") == "absent" else hits > 0
        label = (
            f"{item['key']} (-{item['after']})"
            if item.get("mode") == "absent"
            else (f"{item['key']} (+{item['after']})" if not item["before"] else item["key"])
        )
        (outcome.verified if landed else outcome.not_landed).append(label)

    # Collateral damage: a fact this document carries that was *not* meant to
    # change, was literally present before, and is not present now. Checking
    # only what changed cannot see this, and on a live run it did not — an
    # instruction to update the retry backoff also rewrote a request timeout
    # that happened to read the same, and the report said OK.
    for item in job.invariants:
        if occurrences(text, item["value"]) == 0:
            outcome.collateral.append(f"{item['key']} (\"{item['value']}\" is gone)")
    outcome.unverified = [item["key"] for item in job.unverifiable]

    if not write_back:
        outcome.write_back_skipped = "--no-write-back"
        return
    if outcome.not_landed or outcome.collateral:
        why = ", ".join(outcome.not_landed + outcome.collateral)
        outcome.write_back_skipped = (
            f"verification failed for {why}; the file was left alone"
        )
        return

    target = Path(state.root) / job.path
    if not force_write and _has_foreign_edits(state, job.path, target):
        outcome.write_back_skipped = (
            "the file has uncommitted changes that this tool did not make; re-run with "
            "--force-write to overwrite them"
        )
        return

    note(job.path, "exporting to markdown")
    body, warnings = client.export_html(document_html, fmt="markdown")
    markdown = body.decode("utf-8", errors="replace")
    if not markdown.strip():
        outcome.write_back_skipped = "the markdown export came back empty"
        return
    for warning in warnings:
        log.warning("export warning on %s: %s", job.path, warning)

    updated = job.front_matter + markdown.lstrip("\n")
    if not updated.endswith("\n"):
        updated += "\n"
    target.write_text(updated, encoding="utf-8")
    outcome.written_back = True
    state.record_upload(
        job.path, job.document_id, content_hash(updated), job.title, session_id=job.session_id
    )
    state.mark_written(job.path, content_hash(updated))


# ---------------------------------------------------------------------------


def apply_interactive(
    client: SuperDocs,
    plan: ChangePlan,
    state: State,
    *,
    session_prefix: str,
    review: Reviewer,
    model_tier: str = "pro",
    write_back: bool = True,
    force_write: bool = False,
    poll_timeout: float = 420.0,
    on_progress: Progress = None,
) -> tuple[Pending, ApplyReport]:
    """stage → ask a person → commit, in one process. What the CLI runs."""
    pending = stage(
        client,
        plan,
        state,
        session_prefix=session_prefix,
        model_tier=model_tier,
        poll_timeout=poll_timeout,
        on_progress=on_progress,
    )
    decisions: dict[str, bool] = {}
    for job in pending.jobs:
        for change in job.changes:
            decisions[change.change_id] = review(change, job)
    report = commit(
        client,
        pending,
        state,
        decisions=decisions,
        write_back=write_back,
        force_write=force_write,
        poll_timeout=poll_timeout,
        on_progress=on_progress,
    )
    pending.clear()
    return pending, report


# ---------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t ]+")


def to_text(value: object) -> str:
    """HTML to plain text, for containment checks and for showing a diff.

    Block boundaries become newlines before tags are stripped. Without that a
    table row collapses to ``Max attempts30`` and a token-boundary search for
    ``30`` correctly finds nothing — a verification failure invented entirely
    by the text conversion.
    """
    if not value:
        return ""
    raw = str(value)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|pre|blockquote)>", "\n", raw)
    raw = re.sub(r"(?i)</(td|th)>", " ", raw)
    raw = _TAG.sub("", raw)
    raw = html_module.unescape(raw)
    raw = _WS.sub(" ", raw)
    return "\n".join(line.strip() for line in raw.splitlines()).strip()
