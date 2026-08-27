"""Answering "did that actually happen?" after a crash, without guessing.

A ``SIGKILL`` between sending a request and recording its answer leaves a question that
local state cannot settle: the process that knew is gone. Longhaul settles it by asking
SuperDocs, using evidence that outlives both the process and the job:

1. **The job**, via ``GET /v1/jobs/{job_id}`` — precise, but jobs are purged one hour
   after creation, so this can never be the only route.
2. **The session transcript**, via ``GET /v1/sessions/{id}/history`` — every step's
   instruction carries an idempotency token, and a turn that reached the server left that
   token in the transcript. History does not expire.
3. **The document itself** — the pre-state hash recorded before the turn tells us whether
   anything was actually committed.

When those three cannot agree on an answer, the verdict is ``inconclusive`` and the run
halts for a human. Guessing in either direction is worse than stopping: guess "landed"
and a step is silently skipped, guess "not landed" and an edit is applied twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .client import Job, SuperDocsClient, SuperDocsError
from .model import Step, sha256_text

# --- issue-window (W1) outcomes ------------------------------------------

#: The turn never reached the server. Safe to issue.
NOT_LANDED = "not_landed"
#: The turn landed and its job is still readable. Adopt it; never re-issue.
LANDED_RECOVERABLE = "landed_recoverable"
#: The turn landed, its job is gone, and the document proves nothing was committed.
#: Re-issuing is provably a no-op against document state, and is recorded as such.
LANDED_EXPIRED_NOOP = "landed_expired_noop"
#: Evidence disagrees or is missing. Halt.
INCONCLUSIVE = "inconclusive"

# --- commit-window (W2) outcomes -----------------------------------------

COMMIT_LANDED = "commit_landed"
#: The approve landed and the model came back with a further round for the same turn.
COMMIT_LANDED_NEXT_ROUND = "commit_landed_next_round"
COMMIT_NOT_LANDED = "commit_not_landed"
COMMIT_EXPIRED = "commit_expired"


_TOKEN_RE = re.compile(r"\[longhaul:\d+:[0-9a-f]+\]")


@dataclass(frozen=True)
class SessionSweep:
    """What SuperDocs already knows about this run, read once before doing anything.

    Both reads are free, and together they close a hole that killing the *process* never
    exposes: a ledger that is behind the server. If the ledger is lost, restored from a
    backup, or rolled back, a step can read ``PLANNED`` while its turn has in fact already
    been issued. Re-issuing it would apply the edit twice — the exact failure this project
    exists to prevent — so every step checks the transcript before it issues, not only the
    ones the ledger admits were in flight.
    """

    #: token -> job_id, when the mapping can be established without guessing.
    tokens: dict[str, str]
    #: every step token present in the session transcript.
    landed: frozenset[str]
    #: the job currently holding the session open for review, if any.
    pending_job: str | None

    @staticmethod
    def empty() -> "SessionSweep":
        return SessionSweep({}, frozenset(), None)


def sweep_session(client: SuperDocsClient, session_id: str) -> SessionSweep:
    """Read the transcript and the job list, and attribute one to the other.

    Attribution is by chronological position: a run issues one turn at a time under an
    exclusive lease, so the Nth tokened user message is the Nth chat job. If the two lists
    do not line up exactly, no mapping is produced rather than a plausible-looking guess —
    the caller then falls back to the slower evidence ladder.
    """
    try:
        history = client.session_history(session_id, include_document_html=False)
    except SuperDocsError:
        return SessionSweep.empty()

    ordered: list[str] = []
    for message in sorted(history.get("messages") or [],
                          key=lambda m: m.get("turn_index") or 0):
        if message.get("role") != "user":
            continue
        found = _TOKEN_RE.search(message.get("content") or "")
        if found:
            ordered.append(found.group(0))

    try:
        rows = [j for j in client.session_jobs(session_id)
                if (j.get("job_type") or "chat") == "chat"]
    except SuperDocsError:
        rows = []
    rows.sort(key=lambda j: j.get("created_at") or "")

    pending = next(
        (j.get("job_id") for j in rows if j.get("status") == "awaiting_approval"), None
    )
    mapping: dict[str, str] = {}
    if rows and len(rows) == len(ordered):
        mapping = {t: j.get("job_id", "") for t, j in zip(ordered, rows)}

    return SessionSweep(tokens=mapping, landed=frozenset(ordered), pending_job=pending)


@dataclass(frozen=True)
class Verdict:
    outcome: str
    evidence: str
    job: Job | None = None

    @property
    def is_conclusive(self) -> bool:
        return self.outcome != INCONCLUSIVE


def resolve_issue(
    client: SuperDocsClient,
    session_id: str,
    step: Step,
    *,
    document_id: str | None,
    claimed_job_ids: frozenset[str] = frozenset(),
) -> Verdict:
    """Did this step's chat turn reach SuperDocs? (Window W1.)

    ``claimed_job_ids`` are jobs already recorded against other steps of this run. A job
    on the session that no step has claimed can only belong to the step that was in
    flight when the process died, because a run executes its steps one at a time under an
    exclusive lease.
    """
    job = _try_job(client, step.job_id)
    if job is not None:
        return Verdict(
            LANDED_RECOVERABLE,
            f"job {job.job_id} is readable with status {job.status!r}",
            job,
        )

    # No job id recorded, or the job has been purged. Fall back to the transcript, which
    # is the only evidence that survives an outage longer than the job TTL.
    try:
        landed, where = _token_in_history(client, session_id, step.token)
    except SuperDocsError as exc:
        return Verdict(INCONCLUSIVE, f"session history unreadable: {exc}")

    if not landed:
        return Verdict(
            NOT_LANDED,
            f"token {step.token} absent from the session transcript ({where})",
        )

    # The turn landed. Before concluding anything about the document, try to get a handle
    # on the job itself — this is the crash where the request went out and the job id
    # never reached the ledger.
    if step.job_id is None:
        adopted = _adopt_orphan_job(client, session_id, claimed_job_ids)
        if adopted is not None:
            return Verdict(
                LANDED_RECOVERABLE,
                f"turn landed ({where}); adopted unclaimed session job {adopted.job_id} "
                f"(status {adopted.status!r}) rather than issuing a second turn",
                adopted,
            )

    # The turn landed and its job is unreachable. Whether re-issuing is safe now depends
    # entirely on whether anything was committed, and the document answers that.
    if step.job_id is None:
        detail = "no job id was recorded before the crash and no unclaimed job remains"
    else:
        detail = f"job {step.job_id} has been purged"

    if step.pre_hash is None:
        return Verdict(
            INCONCLUSIVE,
            f"turn landed ({where}) and {detail}, and no pre-state hash was recorded",
        )
    try:
        current = document_hash(client, session_id, document_id)
    except SuperDocsError as exc:
        return Verdict(INCONCLUSIVE, f"turn landed ({where}) but document unreadable: {exc}")

    if current == step.pre_hash:
        return Verdict(
            LANDED_EXPIRED_NOOP,
            f"turn landed ({where}), {detail}, and the document is byte-for-byte at the "
            f"recorded pre-state, so nothing was committed",
        )
    return Verdict(
        INCONCLUSIVE,
        f"turn landed ({where}), {detail}, and the document has moved off the recorded "
        f"pre-state; whether this step's changes are part of that cannot be established",
    )


def resolve_commit(
    client: SuperDocsClient,
    session_id: str,
    step: Step,
    *,
    document_id: str | None,
    decided_change_ids: frozenset[str] = frozenset(),
) -> Verdict:
    """Did this step's approve reach SuperDocs? (Window W2.)

    Cheaper than W1: an approve names ``change_id``s that already exist as proposals, so
    replaying one cannot invent an edit. The only question is whether to replay it.
    """
    job = _try_job(client, step.job_id)
    if job is not None:
        if job.status == "completed":
            return Verdict(COMMIT_LANDED, f"job {job.job_id} is completed", job)
        if job.status == "awaiting_approval":
            # "Awaiting approval" is ambiguous once a turn can need several rounds. If the
            # changes on offer are ones we already decided, our approve never landed. If
            # they are new, it landed and the model has moved on to the next part of the
            # same edit — replaying the approve there would commit the earlier round twice.
            pending = {c.get("change_id") for c in job.pending_changes() if c.get("change_id")}
            if pending and decided_change_ids and not (pending & decided_change_ids):
                return Verdict(
                    COMMIT_LANDED_NEXT_ROUND,
                    f"job {job.job_id} is awaiting approval on {len(pending)} change(s) "
                    f"we have not seen, so the previous approve committed and a further "
                    f"round has begun",
                    job,
                )
            return Verdict(
                COMMIT_NOT_LANDED,
                f"job {job.job_id} is still awaiting approval on changes already decided; "
                f"the approve did not land",
                job,
            )
        if job.status == "failed":
            return Verdict(INCONCLUSIVE, f"job {job.job_id} failed: {job.error}", job)
        return Verdict(COMMIT_NOT_LANDED, f"job {job.job_id} is {job.status!r}", job)

    if step.pre_hash is None:
        return Verdict(INCONCLUSIVE, "job unreadable and no pre-state hash was recorded")
    try:
        current = document_hash(client, session_id, document_id)
    except SuperDocsError as exc:
        return Verdict(INCONCLUSIVE, f"job unreadable and document unreadable: {exc}")

    if current == step.pre_hash:
        # Nothing was applied and the proposals are gone with the job. The step cannot be
        # completed as planned, and inventing a fresh turn here would be a different edit
        # than the one a human approved. That is a decision for a person.
        return Verdict(
            COMMIT_EXPIRED,
            "the approval window expired with the document still at its pre-state; the "
            "approved proposals no longer exist and cannot be committed",
        )
    return Verdict(
        COMMIT_LANDED,
        "job unreadable, but the document has advanced past the recorded pre-state and "
        "this run holds the only lease on it, so the approve committed",
    )


def document_hash(
    client: SuperDocsClient, session_id: str, document_id: str | None
) -> str:
    """Content hash of one open document, read back from the server."""
    for doc in client.session_documents(session_id, include_html=True):
        if doc.get("document_id") == document_id:
            return sha256_text(doc.get("html") or "")
    raise SuperDocsError(
        f"document {document_id} is not open in session {session_id}",
        fix="the run's documents must stay open in its session for the whole job",
    )


def _adopt_orphan_job(
    client: SuperDocsClient, session_id: str, claimed_job_ids: frozenset[str]
) -> Job | None:
    """Find the job left behind by a step that died before recording its id.

    Only an *unambiguous* orphan is adopted. If the session has more than one unclaimed
    chat job, the mapping from job to step cannot be established from the outside, and
    adopting the wrong one would be a guess. In that case this returns ``None`` and the
    caller falls through to the document-state argument or to inconclusive.
    """
    try:
        rows = client.session_jobs(session_id)
    except SuperDocsError:
        return None
    orphans = [
        r for r in rows
        if r.get("job_id") not in claimed_job_ids
        and r.get("job_type", "chat") == "chat"
    ]
    if len(orphans) != 1:
        return None
    row = orphans[0]
    return Job(
        job_id=row.get("job_id", ""),
        status=row.get("status", "unknown"),
        metadata=row.get("metadata") or {},
        result=row.get("result"),
        error=row.get("error"),
    )


def _try_job(client: SuperDocsClient, job_id: str | None) -> Job | None:
    if not job_id:
        return None
    try:
        return client.get_job(job_id)
    except SuperDocsError:
        return None


def _token_in_history(
    client: SuperDocsClient, session_id: str, token: str
) -> tuple[bool, str]:
    history = client.session_history(session_id, include_document_html=False)
    messages = history.get("messages", []) or []
    for message in messages:
        if message.get("role") != "user":
            continue
        if token in (message.get("content") or ""):
            return True, f"turn {message.get('turn_index')} of the session transcript"
    return False, f"{len(messages)} messages scanned"
