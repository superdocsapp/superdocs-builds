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
    client: SuperDocs, publication: Publication, instruction: str
) -> tuple[list[ProposedChange], list[dict[str, Any]]]:
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
    return edit_each(client, publication, dict.fromkeys(publication.document_ids, instruction))


def edit_each(
    client: SuperDocs, publication: Publication, instructions: dict[str, str]
) -> tuple[list[ProposedChange], list[dict[str, Any]]]:
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
        outstanding = client.active_jobs(publication.session_for(document_id))
        if not outstanding:
            continue
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
            instruction, publication.session_for(document_id), document_id=document_id
        )
        started.append((document_id, job_id))

    changes: list[ProposedChange] = []
    replies: list[dict[str, Any]] = []
    for document_id, job_id in started:
        job = client.wait_for_job(job_id)
        replies.append(job)
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


def assert_touched_both(publication: Publication, changes: list[ProposedChange]) -> None:
    """Refuse a batch that would leave the pair disagreeing.

    An edit to a fact that appears in both documents must propose changes to
    both. If it did not, applying it produces exactly the divergence this build
    exists to prevent -- so the batch is rejected rather than half-applied.
    """
    grouped = changes_by_document(publication, changes)
    empty = [
        publication.name_for(doc_id) for doc_id in publication.document_ids if not grouped[doc_id]
    ]
    if empty:
        raise SuperDocsError(
            "this edit proposed no change to the "
            + " or the ".join(empty)
            + ". Applying it would leave the manual and the card disagreeing, "
            "so nothing was approved. Either the fact does not appear in that "
            "document, or the instruction was too narrow."
        )


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


def swap_diagrams(
    client: SuperDocs, publication: Publication, spec: Spec
) -> tuple[list[ProposedChange], dict[str, str], dict[str, dict[str, str]]]:
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
    instructions = {
        document_id: _swap_instruction(captions, expected)
        for document_id, captions in asked.items()
        if captions
    }

    changes, _ = edit_each(client, publication, instructions)
    return changes, expected, {document_id: asked[document_id] for document_id in instructions}


def _swap_instruction(captions: dict[str, str], expected: dict[str, str]) -> str:
    lines = "\n".join(
        f'- the figure whose caption is "{caption}": set its <img src> to {expected[caption]}'
        for caption in captions
        if caption in expected
    )
    return (
        "Update the diagram image URLs. Make exactly these substitutions and "
        "nothing else -- do not reword, reformat, or renumber anything, do not "
        "change any caption or alt text, and do not touch a figure that is not "
        "listed:\n" + lines
    )


def assert_every_figure_swapped(
    changes: list[ProposedChange], asked: dict[str, dict[str, str]]
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
    seen: dict[str, set[str]] = {}
    for change in changes:
        for caption, _ in images_in(change.new_html):
            seen.setdefault(change.document_id or "", set()).add(caption)

    for document_id, captions in asked.items():
        missing = sorted(set(captions) - seen.get(document_id, set()))
        if missing:
            raise SuperDocsError(
                f"{len(missing)} figure(s) in {document_id} were not swapped: "
                + ", ".join(repr(caption) for caption in missing)
                + ". They still point at the old drawing, so approving this "
                "batch would leave the two documents showing different "
                "diagrams. Nothing was approved."
            )


_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r'\bsrc="([^"]*)"', re.I)
_ALT = re.compile(r'\balt="([^"]*)"', re.I)


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
    "Publication",
    "approve_all",
    "assert_every_figure_swapped",
    "assert_only_the_image_changed",
    "assert_touched_both",
    "changes_by_document",
    "edit_both",
    "edit_each",
    "images_in",
    "publish",
    "refresh_diagrams",
    "render_diagrams",
    "swap_diagrams",
    "upload_diagrams",
]
