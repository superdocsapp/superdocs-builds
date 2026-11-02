"""Publishing the pair, and editing it without letting the two drift apart.

Two ways an edit reaches these documents, and the split is deliberate.

**Structural edits go through the spec.** Adding a part, renumbering the
assembly, changing which steps the card carries -- these change the diagrams, so
they are made in `spec/*.yaml`, regenerated, and re-published. A model is never
asked to redraw anything.

**Wording edits go through one instruction, run against both documents.** "Raise
the rail torque to 1.6 N·m" is the edit that actually happens to a shipped
manual, and it is exactly where a manual and its quick-start card come apart:
someone edits one and forgets the other.

The shape of that took three attempts against the live service, and the two
dead ends are worth keeping written down because both of them *looked* like they
worked.

*One turn naming both documents.* The API takes `document_ids` without
complaint, comes back with proposed changes, and puts every one of them in the
focused document. The card is untouched and nothing says so. There is no call
that edits two documents at once.

*Two turns in one session.* The first parks at `awaiting_approval`, which holds
the session, and the second is refused with 409 `session_busy`. A pair sharing a
session cannot have both halves proposed at the same time -- and both halves
proposed at the same time is the entire point.

So: **a session per document**, both turns sent before either is waited on, and
nothing applied until both have proposed. The guarantee was never really in the
single request; it was in the fact that approval is one decision and approval is
the only thing that mutates. `changes_by_document` and `assert_touched_both` are
how a caller checks the pair actually moved together rather than trusting it.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from manualbuilder import diagram
from manualbuilder import projections as pj
from manualbuilder.spec import Spec
from manualbuilder.superdocs import ProposedChange, SuperDocs, SuperDocsError


@dataclass
class Publication:
    """What was published, and enough to edit it again.

    A document has two ids and they are not interchangeable. `doc_c8c07c4a91` is
    scoped to a session and is what a chat turn names; the UUID underneath it is
    the durable one, and is what opens the document somewhere else. Asking for a
    session-scoped id in another session returns *"None of the requested
    documents were found"*, which reads like the document is gone.
    """

    manual_id: str
    card_id: str
    images: dict[str, str] = field(default_factory=dict)
    #: document id -> the session that document is edited in. One session each,
    #: because a session runs one turn at a time and a batch parked at
    #: `awaiting_approval` blocks the next turn in that session -- so a pair
    #: sharing a session cannot have both halves proposed at once, which is the
    #: whole point of the pair.
    sessions: dict[str, str] = field(default_factory=dict)
    #: document id -> its durable id, for opening it elsewhere later.
    durable: dict[str, str] = field(default_factory=dict)
    #: document id -> the job its last turn produced. Approving needs the job
    #: the changes came from, so both are kept until the batch is decided.
    jobs: dict[str, str] = field(default_factory=dict)

    def session_for(self, document_id: str) -> str:
        session_id = self.sessions.get(document_id)
        if not session_id:
            raise SuperDocsError(
                f"no session recorded for {document_id}; `publish` opens one per "
                f"document and writes it down"
            )
        return session_id

    def durable_for(self, document_id: str) -> str:
        """The id that identifies this document anywhere, not just in a session.

        `doc_c8c07c4a91` means something only inside the session it came from.
        The UUID underneath it is what `GET /v1/documents/{id}` takes, and is
        therefore what any read that must not come back holding a different
        document has to use.
        """
        durable = self.durable.get(document_id)
        if not durable:
            raise SuperDocsError(
                f"no durable id recorded for {document_id}; it cannot be read "
                f"by id, only through whatever its session happens to be "
                f"focused on. Re-run `publish`."
            )
        return durable

    def reopen(self, client: SuperDocs) -> None:
        """Put each document in a fresh session, discarding the conversation.

        A session is a conversation and it remembers. An instruction sent into
        one that has already discussed a torque figure gets read in the light of
        that torque figure -- which is right for a person and wrong for a
        mechanical operation, and it showed: a diagram-URL swap kept proposing
        an edit to the paragraph that an earlier turn in that session had
        proposed and had had rejected.

        So work that is meant to be mechanical gets a conversation with no
        history in it. The documents are durable and unaffected; only the chat
        around them is thrown away.
        """
        for document_id in self.document_ids:
            self.sessions[document_id] = self._open_fresh(client, document_id)

    def _open_fresh(self, client: SuperDocs, document_id: str) -> str:
        """A new session holding this document and nothing else."""
        durable = self.durable.get(document_id)
        if not durable:
            raise SuperDocsError(
                f"no durable id recorded for {document_id}, so it cannot be "
                f"opened in a new session; re-run `publish`"
            )
        session_id = client.init_session([durable])
        held = [d.get("document_id") for d in client.documents(session_id)]
        if held != [document_id]:
            raise SuperDocsError(
                f"a fresh session for {document_id} came back holding "
                f"{held}; the turn would be sent to the wrong document"
            )
        return session_id

    def ensure_sessions(self, client: SuperDocs) -> list[str]:
        """Re-bind any document whose session has stopped holding it.

        Returns the documents that had to be moved.

        A session is not a stable handle on a document, and export is keyed by
        session: it renders what the session is *focused* on. Open the pair in
        the web interface and focus the other tab, and the session this program
        recorded for the card starts serving the manual -- same call, same
        session id, different document, no error. That happened, and `verify`
        reported the card as having eight figures and disagreeing with the
        manual, which was true of the document it was handed and nothing to do
        with the card.

        So the recorded session is checked against what it actually holds before
        anything is read out of it, and a document that has drifted is re-opened
        by its durable id -- the id that does identify a document.
        """
        moved: list[str] = []
        for document_id in self.document_ids:
            session_id = self.sessions.get(document_id)
            held: list[str | None] = []
            if session_id:
                try:
                    held = [d.get("document_id") for d in client.documents(session_id)]
                except SuperDocsError:
                    held = []  # gone, or not ours any more; re-open it
            if held == [document_id]:
                continue
            self.sessions[document_id] = self._open_fresh(client, document_id)
            moved.append(document_id)
        return moved

    @property
    def document_ids(self) -> list[str]:
        return [self.manual_id, self.card_id]

    def name_for(self, document_id: str) -> str:
        if document_id == self.manual_id:
            return "manual"
        if document_id == self.card_id:
            return "quick-start card"
        return document_id

    def document_named(self, name: str) -> str:
        """The inverse of `name_for`, for a check that reports by role."""
        for document_id in self.document_ids:
            if self.name_for(document_id) == name:
                return document_id
        raise SuperDocsError(f"this publication has no document called {name!r}")


def render_diagrams(spec: Spec) -> dict[str, str]:
    """Every diagram the documents reference, as SVG, keyed by diagram id."""
    out = {pj.BREAKDOWN: diagram.exploded(spec)}
    for step in spec.steps:
        out[pj.step_image_id(step)] = diagram.for_step(spec, step)
    return out


def upload_diagrams(client: SuperDocs, spec: Spec) -> dict[str, str]:
    """Render and upload, returning diagram id -> URL.

    Iterates `projections.image_ids` so the set uploaded is exactly the set the
    documents reference. A diagram uploaded but never referenced is wasted quota;
    one referenced but never uploaded is a broken image in a shipped manual.
    """
    svgs = render_diagrams(spec)
    urls: dict[str, str] = {}
    for image_id in pj.image_ids(spec):
        filename = image_id.replace(":", "_") + ".svg"
        urls[image_id] = client.upload_image(filename, svgs[image_id])
    return urls


def publish(client: SuperDocs, spec: Spec, language: str = "") -> Publication:
    """Upload the diagrams, then both documents that reference them.

    `language` only names the files. What makes these the German documents is
    that `spec` is the German spec -- including its drawings, which are rendered
    from a parts graph carrying German labels rather than being the English ones
    with a translation around them.
    """
    images = upload_diagrams(client, spec)
    suffix = f"-{language}" if language else ""

    published = Publication(manual_id="", card_id="", images=images)
    for role, filename, html in (
        ("manual", f"{_slug(spec.name)}-manual{suffix}.html", pj.manual_html(spec, images)),
        ("card", f"{_slug(spec.name)}-quickstart{suffix}.html", pj.quick_start_html(spec, images)),
    ):
        # A session each. Sharing one would be tidier and would mean the pair
        # could never have both halves proposed at the same time: the first
        # turn parks at `awaiting_approval` and the session refuses the second
        # with 409 `session_busy`.
        session_id = client.init_session()
        document_id = client.upload(filename, html, session_id=session_id, open_mode="new_focused")

        held = client.documents(session_id)
        if [d.get("document_id") for d in held] != [document_id]:
            raise SuperDocsError(
                f"the {role}'s session holds {[d.get('document_id') for d in held]} "
                f"rather than {document_id} alone; an edit would reach the wrong "
                f"document"
            )

        setattr(published, f"{role}_id" if role == "manual" else "card_id", document_id)
        published.sessions[document_id] = session_id
        published.durable[document_id] = str(held[0].get("durable_document_id") or "")
    return published


def edit_both(
    client: SuperDocs,
    publication: Publication,
    instruction: str,
    thinking_depth: str | None = None,
) -> tuple[list[ProposedChange], dict[str, dict[str, Any]]]:
    """One instruction, both documents, nothing applied by either turn.

    The wording case: "raise the rail torque to 1.6 N·m" is one sentence and it
    is true of both documents, so both get it verbatim. `edit_each` is the same
    machinery for the case where the two need to be asked different things.

    Two turns, because the service edits one document per turn. That is not the
    design this started with -- it started with one turn naming both documents,
    which the API accepts, which returns proposed changes, and every one of
    which lands in the focused document. The card was never touched and the
    reply gave no sign of it.

    So the guarantee moved to where it actually holds. It was never really the
    single request that kept the pair together; it was that **nothing is applied
    until both documents have proposed the change**. Both turns park at
    `awaiting_approval`, `assert_touched_both` looks at the pair, and approval
    covers both or neither. There is still no window in which the manual has
    moved and the card has not, because the window opens at approval and
    approval is one decision.

    A session each, and both turns sent before either is waited on: they are
    different conversations, so they run at the same time and the pair costs one
    wait rather than two.
    """
    return edit_each(
        client,
        publication,
        dict.fromkeys(publication.document_ids, instruction),
        thinking_depth=thinking_depth,
    )


def _refuse_if_busy(client: SuperDocs, publication: Publication, document_id: str) -> None:
    """Refuse to send a turn into a session that already holds one.

    Shared by `edit_each` and `ask`: a batch nobody decided on holds its
    session open, and the service answers the next turn with 409
    `session_busy` -- correct, and four frames deep in a stack trace. Checked
    here instead, where the answer can name what is in the way.
    """
    outstanding = client.active_jobs(publication.session_for(document_id))
    if not outstanding:
        return
    waiting = [job for job in outstanding if job.get("status") == "awaiting_approval"]
    raise SuperDocsError(
        f"the {publication.name_for(document_id)} already has "
        f"{len(outstanding)} turn(s) in flight"
        + (
            f", {len(waiting)} waiting to be approved. Run `approve` to apply "
            f"that batch or `approve --discard` to throw it away; a proposal "
            f"nobody decided on blocks every later edit."
            if waiting
            else ". Wait for it to finish -- deep operations run minutes, and a "
            "second turn sent now would be refused rather than queued."
        )
    )


def ask(
    client: SuperDocs,
    publication: Publication,
    document_id: str,
    question: str,
    thinking_depth: str = "fast",
) -> dict[str, Any]:
    """A read-only turn against one document: the answer, not a proposal.

    `edit_both` is the wrong shape for a question. It always targets the pair,
    so asking about the manual would needlessly cost a second turn against the
    card, and its callers only ever look at `pending_changes` -- a plain answer
    in `response` is fetched off the API and then thrown away. This asks one
    document, through the synchronous endpoint (a question does not need a
    poll loop, since there is no batch to wait on), and hands back the reply
    whole so the caller can read `response` and still notice if the turn
    proposed something anyway.

    `thinking_depth="fast"` by default: a question is not an edit, and a live
    check against all three depths answered this build's own probe question
    identically at `fast`, `balanced` and `deep` -- the depth was never what
    was at risk here. `fast` runs roughly a sixth of the reasoning tokens
    `balanced` (the server's default) would spend, per
    docs.superdocs.app/guides/model-selection. A caller who wants deeper
    reasoning on a harder question can still pass `thinking_depth="deep"`.

    Asked in a session of its own, opened fresh and never recorded on the
    publication -- the same shape `swap_diagrams` uses for the same reason.
    `edit`'s session is deliberately conversational, because a later edit can
    reasonably benefit from remembering an earlier one; a question does not
    need that, and the risk runs the other way besides. In the one live run
    that found this, a question about the rail step's torque -- which the
    step's own sentence plainly states -- came back "the document does not
    specify a torque value," and the very next `edit` sent into that same
    session, asked to raise that torque, took its own wrong answer at its
    word: it left the step's sentence untouched and added a second, newly
    invented torque figure to the specifications table instead -- a manual
    that would have shipped disagreeing with itself, past every guard this
    project has, because both documents had proposed *something* and neither
    guard asks whether a document still agrees with its own other page. A
    disposable session does not stop a model being wrong; it stops a wrong
    answer here from being remembered by a session `edit` will use next.
    """
    session_id = publication._open_fresh(client, document_id)
    return client.chat(question, session_id, document_id=document_id, thinking_depth=thinking_depth)


def edit_each(
    client: SuperDocs,
    publication: Publication,
    instructions: dict[str, str],
    thinking_depth: str | None = None,
) -> tuple[list[ProposedChange], dict[str, dict[str, Any]]]:
    """A turn per document, each with its own instruction.

    Same machinery as `edit_both` and a different question per document, which
    the diagram swap needs: the manual holds eight figures and the card holds
    one, and the list of substitutions is therefore not the same list. Sending
    the union to both is what broke the card -- asked to swap seven figures it
    does not contain, the turn stopped and asked which ones were meant, and
    changed nothing at all.

    A document named with no instruction is not sent a turn. A document with no
    figures in it has nothing to say about a diagram refresh, and a turn that
    costs quota to be told that is a turn not worth sending.
    """
    # A batch nobody decided on holds its session open, and the service answers
    # the next turn with 409 `session_busy` -- correct, and four frames deep in
    # a stack trace. Checked here, where the answer can name what is in the way.
    for document_id in instructions:
        _refuse_if_busy(client, publication, document_id)

    # Both turns are sent before either is waited on. They are in different
    # sessions, so they run at the same time rather than one after the other,
    # and the pair costs one wait instead of two.
    started: list[tuple[str, str]] = []
    for document_id, instruction in instructions.items():
        # Async, not `/v1/chat`, and this is the whole reason the human gate
        # works at all. The synchronous endpoint returns proposed changes and
        # its job goes straight to `completed` -- approving against it comes
        # back "Job is not awaiting approval (status: completed)", so the
        # changes it just showed you can never be applied. `/v1/chat/async`
        # parks its job at `awaiting_approval` with the same changes in
        # `metadata.pending_changes`, and that job is what approval needs.
        job_id = client.chat_async(
            instruction,
            publication.session_for(document_id),
            document_id=document_id,
            thinking_depth=thinking_depth,
        )
        started.append((document_id, job_id))

    changes: list[ProposedChange] = []
    replies: dict[str, dict[str, Any]] = {}
    for document_id, job_id in started:
        job = client.wait_for_job(job_id)
        # Keyed by document rather than a list in send order: the caller that
        # wants a reply wants *this document's* reply, and a document that
        # proposed nothing is exactly the case where the words matter.
        replies[document_id] = job
        turn = client.pending_changes(job)
        if turn:
            publication.jobs[document_id] = job_id
        changes += turn
    return changes, replies


def discard_outstanding(client: SuperDocs, publication: Publication) -> int:
    """Deny every batch parked in this session. Returns how many changes went.

    Asks the session what is actually outstanding rather than trusting a
    recorded batch, because the two come apart: a proposal file written by an
    earlier run names jobs that have since resolved, while the job really
    holding the session is one this process never saw. Whatever is in the way is
    what has to be cleared.

    Denied, not cancelled: `/v1/jobs/{id}/cancel` refuses a job parked at
    `awaiting_approval` -- there is nothing left to interrupt -- and the way a
    parked batch resolves is by being decided. Denied changes cost no quota.
    """
    denied = 0
    for session_id in dict.fromkeys(publication.sessions.values()):
        for job in client.active_jobs(session_id):
            if job.get("status") != "awaiting_approval":
                continue
            job_id = str(job.get("job_id") or job.get("id"))
            changes = client.pending_changes(job)
            client.approve(
                session_id,
                job_id,
                {change.change_id: False for change in changes},
                approved_by_default=False,
            )
            denied += len(changes)
    return denied


def changes_by_document(
    publication: Publication, changes: list[ProposedChange]
) -> dict[str, list[ProposedChange]]:
    """Group a turn's changes by the document they touch.

    This is the check behind the consistency claim. One instruction that comes
    back having touched only the manual is drift caught before it ships, and the
    caller can refuse the whole batch.
    """
    grouped: dict[str, list[ProposedChange]] = {publication.manual_id: [], publication.card_id: []}
    for change in changes:
        grouped.setdefault(change.document_id or "unknown", []).append(change)
    return grouped


def assert_touched_both(
    publication: Publication,
    changes: list[ProposedChange],
    required: list[str] | None = None,
) -> None:
    """Refuse a batch that would leave the pair disagreeing.

    An edit to a fact that appears in both documents must propose changes to
    both. If it did not, applying it produces exactly the divergence this build
    exists to prevent -- so the batch is rejected rather than half-applied.

    `required` narrows which documents this demands a change from; it
    defaults to both. `assert_touched_both_or_absent` is the caller that
    passes something narrower, having already established that the documents
    left out never held the fact to begin with.
    """
    grouped = changes_by_document(publication, changes)
    required = publication.document_ids if required is None else required
    empty = [publication.name_for(doc_id) for doc_id in required if not grouped[doc_id]]
    if empty:
        raise SuperDocsError(
            "this edit proposed no change to the "
            + " or the ".join(empty)
            + ". Applying it would leave the manual and the card disagreeing, "
            "so nothing was approved. Either the fact does not appear in that "
            "document, or the instruction was too narrow."
        )


def excusably_empty(changes: list[ProposedChange], current_html: str) -> bool:
    """Whether nothing in `current_html` resembles what any of `changes` used
    to read there -- i.e. this document never held the fact that changed
    elsewhere, so it proposing nothing is not the pair coming apart.

    Pure: `current_html` is supplied by the caller (a live read, or a local
    render) rather than fetched here -- the same split `verify.pair_findings`
    already uses to stay testable without a client. Reuses `verify`'s own
    passage matching, at the threshold `verify` is calibrated against real
    edited wording, so "structurally absent" here means the same thing "no
    longer recognisable" means in a `verify` report.

    Imported here rather than at module level: `verify` imports `session`, so
    importing `verify` back at the top of this module would be a cycle.
    """
    from manualbuilder import verify as vf

    candidates = vf.passages(current_html)
    for change in changes:
        needle = vf.text_of(change.old_html)
        if needle and vf.closest(needle, candidates)[1] >= vf.MATCH:
            return False
    return True


def assert_touched_both_or_absent(
    client: SuperDocs, publication: Publication, changes: list[ProposedChange]
) -> list[str]:
    """`assert_touched_both`, except a document that never held the fact to
    begin with is not required to propose anything.

    The strict check alone cannot tell "the card should have changed and
    didn't" (real drift -- refuse) apart from "the card never had this fact"
    (nothing to keep in sync -- refusing buys nothing). A manual-only edit to
    the Specifications table, which `quick_start_blocks` never renders onto
    the card at all, was refused by the strict check with no way through it,
    for a reason that had nothing to do with the pair coming apart.

    So each document that proposed nothing is read back by its durable id
    (free) and asked, via `excusably_empty`, whether anything in it resembles
    what changed elsewhere. One that plausibly held the fact is still
    required to have proposed something, and the strict check still refuses
    the batch if it did not -- this changes nothing about the case it exists
    for. One that structurally could not have held it is excused instead, and
    named in the return value so the caller can say so rather than passing it
    through silently.
    """
    grouped = changes_by_document(publication, changes)
    empty = [doc_id for doc_id in publication.document_ids if not grouped[doc_id]]

    excused = []
    for document_id in empty:
        current = client.document_html(publication.durable_for(document_id))
        if excusably_empty(changes, current):
            excused.append(document_id)

    required = [doc_id for doc_id in publication.document_ids if doc_id not in excused]
    assert_touched_both(publication, changes, required=required)
    return excused


def approve_all(
    client: SuperDocs,
    publication: Publication,
    changes: list[ProposedChange],
    reject: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Approve the batch, minus anything rejected by change id.

    Rejecting one change does not discard the rest, and that is not a nicety.
    Asked to change one torque figure, a turn will find the same number in a
    step that legitimately shares it and offer to change that too -- it happened
    on the first live run of this code, twice. The right answer is to take the
    two changes that were asked for and refuse the third, in one review, which
    is what the per-change `approved` field is for.

    One call per job, because a job is one turn and a turn is one document.
    """
    reject = reject or set()
    if not publication.jobs:
        raise SuperDocsError(
            "no job to approve against; the turns proposed nothing, or "
            "`edit_both` was not the thing that ran them"
        )

    unknown = reject - {change.change_id for change in changes}
    if unknown:
        raise SuperDocsError(
            f"asked to reject {', '.join(sorted(unknown))}, which is not in this "
            f"batch. Approving the rest would apply a change somebody meant to "
            f"stop, so nothing was sent."
        )

    by_job: dict[tuple[str, str], dict[str, bool]] = {}
    for change in changes:
        document_id = change.document_id or ""
        job_id = publication.jobs.get(document_id)
        if not job_id:
            raise SuperDocsError(
                f"change {change.change_id} belongs to document "
                f"{document_id!r}, which no recorded turn produced"
            )
        key = (publication.session_for(document_id), job_id)
        by_job.setdefault(key, {})[change.change_id] = change.change_id not in reject

    # `approved` at the top level is the default for entries that omit their
    # own. Every entry here carries its own, so the default only matters if the
    # service adds a change we did not see -- and False is the safe answer to
    # that.
    return [
        client.approve(session_id, job_id, decisions, approved_by_default=False)
        for (session_id, job_id), decisions in by_job.items()
    ]


#: How long to keep re-reading a document that has not caught up with an
#: approval yet, and how long to wait between reads. Both are wall-clock
#: patience and nothing else: the reads are free, and the alternative to
#: spending twenty seconds here is a `verify` that reports a correct document
#: as wrong. Six seconds was the longest lag seen on a nine-change batch, so
#: the budget is several times that and the loop leaves the moment it agrees.
SETTLE_TIMEOUT = 30.0
SETTLE_POLL = 2.0


@dataclass(frozen=True)
class Settlement:
    """What the read side was serving after an approval, and how long it took.

    `waited` is reported rather than hidden because it is the only evidence a
    caller has that the wait was needed. A run that settles on the first read
    prints nothing; a run that took six seconds is worth a line, and a run that
    never settled is worth a warning.
    """

    waited: float
    reads: int
    #: document id -> the chunks still serving their pre-approval content.
    outstanding: dict[str, list[str]] = field(default_factory=dict)

    @property
    def settled(self) -> bool:
        return not self.outstanding


def arrived(html: str, change: ProposedChange) -> bool:
    """Whether a document read back carries what this change was approved to put in it.

    Not a comparison of the chunk against `new_html`, which would be the
    obvious thing and is the wrong thing: the service reflows what it stores,
    and a chunk that differs only in whitespace or attribute order is the
    approved content, arrived. So it asks the two questions the approval
    actually made a claim about -- the new words are in the document, and every
    image the chunk now points at is one the document is serving.

    Images are compared by URL *path*, for the reason `_same_image` gives: what
    comes back is signed, and the signature differs on every read.
    """
    from manualbuilder import verify as vf

    text = vf.text_of(change.new_html)
    if text and text not in vf.text_of(html):
        return False
    served = {urlparse(src).path for _, src in images_in(html)}
    return all(urlparse(src).path in served for _, src in images_in(change.new_html))


def settle(
    client: SuperDocs,
    publication: Publication,
    changes: list[ProposedChange],
    timeout: float | None = None,
    poll: float | None = None,
) -> Settlement:
    """Read the documents back until they serve what was just approved.

    `approve` returns before the read side agrees with it. Not in theory: a
    nine-change diagram swap came back `200`, every change approved, and the
    next command -- reading each document by its durable id, seconds later --
    got all nine figures still pointing at the previous drawings, then got the
    new ones on a re-read with nothing else done in between. Reported as-is,
    that is `verify` announcing that the documents on the service are not what
    this program published, about a pair that is entirely correct.

    The honest fix is not to skip the check. It is to wait for the thing the
    approval promised before checking it, and to say so when the wait was
    needed -- which is what this does, in free reads, on the same durable ids
    `verify` uses. If the budget runs out, that is reported too: an approval
    the service has accepted and is not serving yet is worth a caller knowing
    about, and it is not something this can fix by looking harder.

    Nothing here is billed.
    """
    # Read from the module rather than bound as defaults, so the budget is one
    # thing to change -- and so a test can shorten it without reaching into a
    # function signature.
    timeout = SETTLE_TIMEOUT if timeout is None else timeout
    poll = SETTLE_POLL if poll is None else poll

    outstanding: dict[str, list[ProposedChange]] = {}
    for change in changes:
        outstanding.setdefault(change.document_id or "", []).append(change)

    started, reads = time.monotonic(), 0
    while True:
        for document_id in list(outstanding):
            html = client.document_html(publication.durable_for(document_id))
            reads += 1
            waiting = [c for c in outstanding[document_id] if not arrived(html, c)]
            if waiting:
                outstanding[document_id] = waiting
            else:
                del outstanding[document_id]

        waited = time.monotonic() - started
        if not outstanding or waited + poll > timeout:
            return Settlement(
                waited=waited,
                reads=reads,
                outstanding={
                    document_id: [c.chunk_id for c in waiting]
                    for document_id, waiting in outstanding.items()
                },
            )
        time.sleep(poll)


def read_pair(client: SuperDocs, publication: Publication) -> dict[str, str]:
    """Both documents as the service is serving them, keyed by role name.

    By durable id, never by session, for the reason `verify` gives at length: a
    session serves whatever it is focused on, and a check that reads the wrong
    document reports on it just as confidently. Free, and unbilled.
    """
    return {
        publication.name_for(document_id): client.document_html(
            publication.durable_for(document_id)
        )
        for document_id in publication.document_ids
    }


# ------------------------------------ the pair, after the batch lands --
#
# `assert_touched_both_or_absent` asks whether each document proposed
# *something*, which is the question that catches a card nobody edited. It is
# not the question that catches this: asked to raise a torque figure, the
# manual's turn found three places -- the rails step, the gantry step, and the
# troubleshooting table's own re-torque line -- and the card's turn found two
# of its three. Both documents proposed something, so the batch passed, and the
# pair came apart on the one passage the card missed. `verify` reported it
# afterwards, correctly and too late.
#
# So the pair is checked passage by passage, on the documents as the service is
# actually serving them, and a passage that moved in one and not the other is
# repaired rather than merely reported: the document that was left behind is
# asked, in one more turn, to say what the other one now says.


def shared_items(spec: Spec) -> list[tuple[str, str, str]]:
    """(kind, id, body) for every passage the card repeats from the manual.

    The list `verify` compares and the list a repair has to cover, in one
    place, because a passage in one and not the other is a passage that gets
    checked and never fixed, or fixed and never checked.
    """
    return [("step", step.id, step.body) for step in spec.quick_start()] + [
        ("fix", fault.id, fault.fix) for fault in spec.quick_start_troubleshooting()
    ]


@dataclass(frozen=True)
class Drift:
    """One passage the two documents no longer word the same way.

    `lagging` is the document that still reads the way the spec words it --
    i.e. the one an edit missed. It is empty when both documents have moved and
    moved differently, which is a disagreement this cannot resolve on its own:
    there is no way to tell which of the two wordings was meant, and picking one
    would be inventing an answer rather than finding it.
    """

    label: str
    lagging: str
    behind: str
    ahead: str

    @property
    def repairable(self) -> bool:
        return bool(self.lagging)


def drifted(served: dict[str, str], spec: Spec) -> list[Drift]:
    """Every shared passage the two documents word differently, and who lags.

    The same comparison `verify.pair_findings` makes and reports; this one
    returns the two wordings, so something can be done about them. Both are
    driven by `shared_items`, so neither can drift out of step with the other.
    """
    from manualbuilder import verify as vf

    if vf.MANUAL not in served or vf.CARD not in served:
        return []

    flat = {role: vf.text_of(served[role]) for role in (vf.MANUAL, vf.CARD)}
    blocks = {role: vf.passages(served[role]) for role in (vf.MANUAL, vf.CARD)}

    out: list[Drift] = []
    for kind, item_id, body in shared_items(spec):
        wanted = vf.needle(body)
        if wanted in flat[vf.MANUAL] and wanted in flat[vf.CARD]:
            continue  # both still word it the way the spec does: nothing moved

        best = {role: vf.closest(wanted, blocks[role]) for role in (vf.MANUAL, vf.CARD)}
        if any(score < vf.MATCH for _, score in best.values()):
            # Rewritten past recognition in at least one of them. `verify` calls
            # that unanswerable rather than failing it, and a repair that
            # guessed here would be writing a passage nobody asked for.
            continue

        manual, card = best[vf.MANUAL][0], best[vf.CARD][0]
        if manual == card:
            continue

        lagging = ""
        if manual == wanted:
            lagging, behind, ahead = vf.MANUAL, manual, card
        elif card == wanted:
            lagging, behind, ahead = vf.CARD, card, manual
        else:
            behind, ahead = manual, card  # both moved; neither is the straggler
        out.append(Drift(f"{kind} {item_id}", lagging, behind, ahead))
    return out


def _align_instruction(drifts: list[Drift]) -> str:
    passages = "\n".join(
        f'- the passage that currently reads:\n    "{drift.behind}"\n'
        f'  must read, exactly:\n    "{drift.ahead}"'
        for drift in drifts
    )
    return (
        "This document was left behind by an edit that has already been applied "
        "to its companion document, and the two now say different things about "
        "the same thing. Make exactly these replacements and nothing else -- do "
        "not reword, reformat or renumber anything else, and do not touch any "
        "other passage, table row, figure or caption:\n" + passages
    )


def realign(
    client: SuperDocs, publication: Publication, drifts: list[Drift]
) -> list[ProposedChange]:
    """Ask each document that was left behind to say what the other one says.

    One turn per document, the same shape every other edit here takes, and the
    same treatment: the wording it has to produce is handed to it verbatim
    rather than described, and what comes back is checked against it before
    anybody is asked to approve anything. A model is being used to locate a
    passage, not to decide what it should say.

    This costs an operation, and it is spent only when the pair has actually
    come apart.
    """
    by_document: dict[str, list[Drift]] = {}
    for drift in drifts:
        if drift.repairable:
            by_document.setdefault(publication.document_named(drift.lagging), []).append(drift)

    if not by_document:
        raise SuperDocsError(
            "both documents have moved, and differently, so there is no "
            "straggler to bring in line. Which wording was meant is a question "
            "for a person: `edit` says it again for both, and `approve --reject` "
            "keeps whichever one is right."
        )

    instructions = {
        document_id: _align_instruction(drifts) for document_id, drifts in by_document.items()
    }
    changes, _ = edit_each(client, publication, instructions)
    assert_only_the_lagging_passage_moved(changes, drifts)
    return changes


def assert_only_the_lagging_passage_moved(
    changes: list[ProposedChange], drifts: list[Drift]
) -> None:
    """Refuse a realignment that changed anything but the passage that lagged.

    The check is exact, and it can be: the chunk's text with the old wording
    swapped for the new one is precisely what the chunk's text has to become.
    A chunk that is a whole troubleshooting table is handled by the same
    sentence -- one row of it moves, and every other row has to come back
    character for character as it went in.
    """
    from manualbuilder import verify as vf

    if not changes:
        raise SuperDocsError(
            "the turn proposed no changes, so the two documents still disagree. "
            "The passage is in the document -- `verify` found it there -- and "
            "the wording to give it was in the instruction verbatim."
        )

    covered: set[str] = set()
    for change in changes:
        before, after = vf.text_of(change.old_html), vf.text_of(change.new_html)
        matched = next(
            (
                drift
                for drift in drifts
                if drift.behind in before and after == before.replace(drift.behind, drift.ahead)
            ),
            None,
        )
        if matched is None:
            raise SuperDocsError(
                f"change {change.change_id} did not make chunk {change.chunk_id} "
                f"read the way the companion document reads. Bringing the pair "
                f"back together is a substitution of one known passage for "
                f"another, so the whole batch was refused.\n"
                f"  before: {before[:160]}\n  after:  {after[:160]}"
            )
        covered.add(matched.label)

    missed = [drift.label for drift in drifts if drift.repairable and drift.label not in covered]
    if missed:
        raise SuperDocsError(
            f"the turn left {', '.join(missed)} exactly as it was, so the two "
            f"documents would still disagree on it after this batch. Nothing "
            f"was approved."
        )


def refresh_diagrams(client: SuperDocs, publication: Publication, spec: Spec) -> dict[str, str]:
    """Re-render every diagram from the graph and re-upload it.

    The second grading criterion, and the reason it is a separate function from
    `edit_both`: a diagram is never edited, it is replaced. No model is in the
    drawing path at all. Getting the new URL into the document is `swap_diagrams`
    below, and that is where the interesting part is.
    """
    fresh = upload_diagrams(client, spec)
    publication.images = fresh
    return fresh


def swap_diagrams(client: SuperDocs, publication: Publication, spec: Spec) -> tuple[
    list[ProposedChange],
    dict[str, str],
    dict[str, dict[str, str]],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    """Re-render, upload, and propose swapping each `<img src>` for the new URL.

    A document already on the service cannot be re-uploaded without becoming a
    different document, so the new URL has to reach the existing chunks, and the
    only edit surface is a chat turn. That means asking a model to perform what
    is really a text substitution -- which is exactly the kind of step this
    project otherwise avoids.

    So it is asked for, and then it is checked. `assert_only_the_image_changed`
    compares each proposed chunk against the one it replaces with the image URLs
    masked out: if a single other character moved, the batch is refused whole.
    The model is allowed to propose the swap and is not trusted to have made it.

    The instruction says, in as many words, that this is a text edit to an
    attribute and not an image operation. Without that a turn reaches for the
    service's image-replacement tool instead, which only accepts files attached
    to that chat, and answers "that file isn't one of this session's
    attachments" having changed nothing -- on the manual in one run and on the
    card in the next, because which path it takes is not stable. The drawings
    are uploaded and hosted before this is ever sent; there is nothing to
    attach.

    It is also asked in a fresh conversation. A session remembers what was
    discussed in it, and a swap sent into the session that handled last week's
    torque correction inherits that discussion -- in practice it re-proposed the
    very change that had been rejected there. Nothing about a URL substitution
    benefits from context, so it gets none.
    """
    publication.reopen(client)
    fresh = refresh_diagrams(client, publication, spec)

    # Keyed by caption, because that is what survives the round trip: the
    # service strips `data-*` when it stores a document, so the figure comes
    # back with nothing on it naming which drawing it is except its alt text.
    expected = {
        caption: fresh[image_id]
        for caption, image_id in pj.captions(spec).items()
        if image_id in fresh
    }

    # A document is asked only about the figures it actually holds. The card
    # holds the breakdown and none of the seven step diagrams, and a card handed
    # the manual's list answers that it can only see one of them and asks which
    # were meant -- politely, and having changed nothing.
    asked = {
        publication.manual_id: pj.captions_in(pj.manual_blocks(spec)),
        publication.card_id: pj.captions_in(pj.quick_start_blocks(spec)),
    }
    # Read each document back first, free, so the instruction can name the
    # chunk that holds each figure rather than describing it.
    current = {
        document_id: client.document_html(publication.durable_for(document_id))
        for document_id in asked
    }
    anchors = {document_id: image_chunks(html) for document_id, html in current.items()}
    instructions = {
        document_id: _swap_instruction(captions, expected, anchors[document_id])
        for document_id, captions in asked.items()
        if captions
    }

    changes, replies = edit_each(client, publication, instructions)
    return (
        changes,
        expected,
        {document_id: asked[document_id] for document_id in instructions},
        replies,
        current,
    )


def _swap_instruction(
    captions: dict[str, str], expected: dict[str, str], anchors: dict[str, str]
) -> str:
    lines = "\n".join(
        f'- in the block whose data-chunk-id is "{anchors[caption]}", set the '
        f'<img> src to {expected[caption]}  (its alt is "{caption}")'
        for caption in captions
        if caption in expected and caption in anchors
    )
    return (
        "Update the diagram image URLs. Each line names a block by its "
        "data-chunk-id, and that block already contains one <img>. Change the "
        "value of that img's src attribute to the URL given, and change nothing "
        "else.\n\n"
        "This is a text edit to an attribute, not an image operation: the "
        "drawings are already hosted at these URLs, so do not attach or upload "
        "anything and do not use an image-replacement tool -- there is nothing "
        "to attach. Do not add an <img> anywhere. Do not put one into a block "
        "that currently holds only text: a figure's caption is stored as its "
        "own paragraph of the same words, and it is not the figure. Do not "
        "change any alt text, caption or wording, and do not touch a block that "
        "is not listed:\n" + lines
    )


def assert_every_figure_swapped(
    changes: list[ProposedChange],
    asked: dict[str, dict[str, str]],
    name: Callable[[str], str] | None = None,
) -> None:
    """Refuse a refresh that left one of the figures pointing at the old drawing.

    The complement of `assert_only_the_image_changed`, and the check that was
    missing. That one asks whether everything that changed was a diagram URL; it
    is satisfied by a turn that changed nothing, so the two together are what a
    refresh actually needs. Without this, a live run swapped all eight figures in
    the manual, none of the one in the card, and reported eight clean swaps --
    which is exactly the manual and the card disagreeing, arrived at through the
    path built to keep them together.
    """
    # `doc_9a9c4e4090` is a session-scoped id and means nothing to a reader --
    # the same document has a different one in every session it is opened in.
    # The caller passes `Publication.name_for` so the refusal can say "manual".
    named = name or (lambda document_id: document_id)

    seen: dict[str, set[str]] = {}
    for change in changes:
        for caption, _ in images_in(change.new_html):
            seen.setdefault(change.document_id or "", set()).add(caption)

    for document_id, captions in asked.items():
        missing = sorted(set(captions) - seen.get(document_id, set()))
        if missing:
            raise SuperDocsError(
                f"{len(missing)} figure(s) in the {named(document_id)} were not swapped: "
                + ", ".join(repr(caption) for caption in missing)
                + ". They still point at the old drawing, so approving this "
                "batch would leave the two documents showing different "
                "diagrams. Nothing was approved."
            )


_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r'\bsrc="([^"]*)"', re.I)
_ALT = re.compile(r'\balt="([^"]*)"', re.I)
_CHUNK_ID = re.compile(r'\bdata-chunk-id="([^"]+)"', re.I)


def _masked(html: str) -> str:
    """The chunk with every image URL blanked, so the rest can be compared.

    Attribute order is not fixed -- this renderer writes `src` before `alt` and
    what comes back writes `alt` first -- so the blanking works inside each
    `<img>` tag rather than on a pattern that assumes an order.
    """
    return _IMG_TAG.sub(lambda m: _SRC.sub('src=""', m.group(0)), html)


def _same_image(one: str, other: str) -> bool:
    """Whether two URLs point at the same uploaded file.

    Compared by path, not by string. What goes into a document is the durable
    URL; what comes back on every read is that URL with a 754-character signed
    query appended, because the service signs image links when it serves them.
    An exact-match comparison therefore refuses a correct swap -- it did, on the
    first live run -- while a comparison that ignored the whole URL would accept
    a wrong one. The path is the identity of the file; the query is the
    service's signature on it.
    """
    return urlparse(one).path == urlparse(other).path


def image_chunks(html: str) -> dict[str, str]:
    """alt text -> the id of the chunk that holds that `<img>`.

    The anchor a swap instruction should use, and the third one tried. Naming
    the *caption* is ambiguous in the stored document: the service keeps a
    figure as `<p><img alt="…"></p>` and its caption as a separate paragraph of
    the same words, so "the figure whose caption is X" matches a block of plain
    text as readily as the image, and a live turn duly replaced the caption
    paragraph with an `<img>` -- caught by `assert_only_the_image_changed`,
    which is the only reason it is a story about a refusal rather than about a
    manual that lost a caption.

    A chunk id is not ambiguous, it is in the document the turn is looking at,
    and it is what the reply comes back keyed by.
    """
    out: dict[str, str] = {}
    for match in _IMG_TAG.finditer(html):
        alt = _ALT.search(match.group(0))
        if not alt:
            continue
        # The nearest `data-chunk-id` before the tag is the block it sits in:
        # chunks are top level and do not nest.
        ids = _CHUNK_ID.findall(html[: match.start()])
        if ids:
            out[alt.group(1)] = ids[-1]
    return out


def images_in(html: str) -> list[tuple[str, str]]:
    """Every image in a chunk as (alt, src), in document order."""
    out: list[tuple[str, str]] = []
    for tag in _IMG_TAG.findall(html):
        alt, src = _ALT.search(tag), _SRC.search(tag)
        out.append((alt.group(1) if alt else "", src.group(1) if src else ""))
    return out


def assert_only_the_image_changed(changes: list[ProposedChange], expected: dict[str, str]) -> None:
    """Refuse a diagram swap that did anything besides swap the diagram.

    Three ways this goes wrong, and all three are refused rather than shown to a
    person to notice: the turn rewrote surrounding prose while it was in there;
    it changed a figure nobody asked it to; or it put a URL in the `src` that is
    not the one just uploaded for that figure -- a plausible-looking URL is the
    single most likely thing for a model to produce here, and it would render as
    a broken image in a shipped manual.
    """
    if not changes:
        raise SuperDocsError(
            "the turn proposed no changes, so the documents still point at the "
            "old diagrams. Nothing was uploaded in vain -- but nothing was "
            "swapped either."
        )

    for change in changes:
        if _masked(change.old_html) != _masked(change.new_html):
            raise SuperDocsError(
                f"change {change.change_id} altered more than the image URL in "
                f"chunk {change.chunk_id}. A diagram refresh is a URL "
                f"substitution and nothing else, so the whole batch was "
                f"refused.\n  before: {change.old_html[:160]}\n"
                f"  after:  {change.new_html[:160]}"
            )

        for caption, source in images_in(change.new_html):
            if caption not in expected:
                raise SuperDocsError(
                    f"change {change.change_id} touched a figure captioned "
                    f"{caption!r}, which was not part of this refresh"
                )
            if not _same_image(source, expected[caption]):
                raise SuperDocsError(
                    f"change {change.change_id} pointed {caption!r} at "
                    f"{source[:80]!r}, which is not the URL uploaded for it. "
                    f"That renders as a broken image in a shipped manual."
                )


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


__all__ = [
    "Drift",
    "Publication",
    "Settlement",
    "approve_all",
    "arrived",
    "ask",
    "assert_every_figure_swapped",
    "assert_only_the_image_changed",
    "assert_only_the_lagging_passage_moved",
    "assert_touched_both",
    "assert_touched_both_or_absent",
    "changes_by_document",
    "drifted",
    "edit_both",
    "edit_each",
    "excusably_empty",
    "image_chunks",
    "images_in",
    "publish",
    "read_pair",
    "realign",
    "refresh_diagrams",
    "render_diagrams",
    "settle",
    "shared_items",
    "swap_diagrams",
    "upload_diagrams",
]
