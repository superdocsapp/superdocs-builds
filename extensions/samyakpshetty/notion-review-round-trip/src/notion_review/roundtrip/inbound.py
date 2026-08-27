"""Inbound logic: match the reviewer's markup to blocks, propose edits, apply approved ones.

These are the provider-driven steps the LangGraph nodes call. Kept as plain functions so they are
easy to test directly and easy to reason about: matching and applying are deterministic; only
proposing spends SuperDocs operations, and it is budget-guarded.
"""

from __future__ import annotations

import re
import time
from html import escape

from lxml import html as lxml_html
from lxml.html import HtmlElement
from pydantic import BaseModel

from notion_review.config import Config
from notion_review.docx_markup import DocxComment, DocxMarkup
from notion_review.domain import (
    BlockMapEntry,
    ChangeOperation,
    ChangeSource,
    ProposalStatus,
    ProposedChange,
    ReviewRound,
    RoundStatus,
)
from notion_review.logging import get_logger
from notion_review.notion.base import NotionClient, NotionError
from notion_review.notion.models import RichText, plain_text, row_cells, splice_plain_edit
from notion_review.superdocs.base import SuperDocsClient, SuperDocsError
from notion_review.superdocs.instructions import (
    EditSpec,
    IntentSpec,
    build_batch_instruction,
    build_intent_instruction,
)
from notion_review.superdocs.models import ApprovalDecision, ChunkDiff, Job, JobStatus

_log = get_logger("notion_review.inbound")

_TERMINAL = frozenset(
    {JobStatus.COMPLETED, JobStatus.AWAITING_APPROVAL, JobStatus.FAILED, JobStatus.CANCELLED}
)


def _norm(text: str) -> str:
    return " ".join(text.split()).strip()


def _clip(text: str, limit: int = 120) -> str:
    """Shorten text for a provenance comment without dropping the sense of the change."""
    text = _norm(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


_URI_RE = re.compile(
    r"\b((?:https?|ftp|mailto|javascript|data|vbscript|file):[^\s<>\"')\]]+)", re.I
)
_DANGEROUS_SCHEMES = frozenset({"javascript", "data", "vbscript", "file"})


def _extract_links(text: str) -> list[str]:
    """URLs an edit introduces, for the approver to see before it lands.

    An edit — a reviewer's, or one SuperDocs' AI wrote from a hostile comment — can smuggle in a
    link (phishing, exfiltration). We surface every URI at the gate, flagging dangerous schemes, so
    a human sees exactly what a change would add. The link is never followed here, only shown.
    """
    seen: dict[str, None] = {}
    for match in _URI_RE.finditer(text):
        uri = match.group(1)
        scheme = uri.split(":", 1)[0].lower()
        seen.setdefault(f"⚠ dangerous scheme: {uri}" if scheme in _DANGEROUS_SCHEMES else uri, None)
    return list(seen)


def plain_text_from_html(html: str) -> str:
    if not html.strip():
        return ""
    element: HtmlElement = lxml_html.fromstring(f"<div>{html}</div>")
    return _norm(str(element.text_content()))


class MatchedEdit(BaseModel):
    """One reviewer change tied to the Notion block it belongs on."""

    notion_block_id: str
    notion_page_id: str = ""
    block_type: str
    chunk_id: str | None
    original_text: str
    proposed_text: str
    reviewer: str
    is_text_change: bool
    comment: str = ""
    cell_index: int | None = None  # table rows: which column the reviewer edited


def match_edits(
    markup: DocxMarkup, block_map: list[BlockMapEntry]
) -> tuple[list[MatchedEdit], list[str]]:
    """Match each changed paragraph to its block by the as-sent text.

    Matching is positional within a text: the *n*-th block carrying a given as-sent text pairs
    with the *n*-th same-text paragraph, in document order. A page with two identical paragraphs
    therefore no longer collapses both edits onto the first block — an edit to the second lands
    on the second. When a change cannot be located (unknown text, or more same-text paragraphs
    than blocks), it is surfaced in the unmatched list, never applied to a guessed block.

    Returns the matched edits and the texts of any changes we could not locate.
    """
    # Group block-map entries by as-sent text, preserving document order.
    entries_by_text: dict[str, list[BlockMapEntry]] = {}
    for entry in block_map:
        entries_by_text.setdefault(_norm(entry.original_text), []).append(entry)

    # A table row is one block, but Word renders each cell as its own paragraph, so a reviewer
    # who edits a cell produces a paragraph whose text is that cell alone and matches no row.
    # Index the cells too, remembering which column each one is, and fall back to this when a
    # paragraph matches no whole block.
    cells_by_text: dict[str, list[tuple[BlockMapEntry, int]]] = {}
    for entry in block_map:
        for column, cell in enumerate(entry.cells):
            cells_by_text.setdefault(_norm(cell), []).append((entry, column))

    # Occurrence ordinal of every paragraph among all same-text paragraphs, in document order.
    # Counting over *all* paragraphs (not just changed ones) is what lets an edit to the second
    # of two identical blocks resolve to the second block rather than the first.
    occurrence: dict[int, int] = {}
    seen: dict[str, int] = {}
    for para in markup.paragraphs:
        key = _norm(para.original_text)
        occurrence[para.index] = seen.get(key, 0)
        seen[key] = occurrence[para.index] + 1

    matched: list[MatchedEdit] = []
    unmatched: list[str] = []
    for para in markup.changes():
        entries = entries_by_text.get(_norm(para.original_text), [])
        ordinal = occurrence[para.index]
        cell_index: int | None = None
        if ordinal < len(entries):
            hit = entries[ordinal]
        else:
            cell_hits = cells_by_text.get(_norm(para.original_text), [])
            if ordinal >= len(cell_hits):
                unmatched.append(para.original_text)  # unlocatable — surfaced, never guessed
                continue
            hit, cell_index = cell_hits[ordinal]
        reviewer = _reviewer_of(para.authors, para.comments)
        matched.append(
            MatchedEdit(
                notion_block_id=hit.notion_block_id,
                notion_page_id=hit.notion_page_id,
                block_type=hit.block_type,
                chunk_id=hit.chunk_id,
                original_text=para.original_text,
                proposed_text=para.proposed_text,
                reviewer=reviewer,
                is_text_change=para.is_text_change,
                comment=" ".join(c.text for c in para.comments),
                cell_index=cell_index,
            )
        )
    return matched, unmatched


def _reviewer_of(authors: list[str], comments: list[DocxComment]) -> str:
    if authors:
        return authors[0]
    if comments and comments[0].author:
        return comments[0].author
    return "Unknown reviewer"


def _is_edit_request(comment: str) -> bool:
    """Whether a comment directs an edit (vs. asks a question only the owner can answer).

    A deliberate, conservative heuristic layered ahead of the AI and the human gate: a question is
    never sent to SuperDocs to author, so the AI cannot fabricate an answer into the document; it is
    surfaced to the owner as a comment instead. The human gate catches anything this misclassifies.
    """
    return not _norm(comment).endswith("?")


def propose_changes(
    round_: ReviewRound,
    superdocs: SuperDocsClient,
    matched: list[MatchedEdit],
    config: Config,
) -> None:
    """Propose each reviewer change through SuperDocs, in batched calls, gated for the human.

    A tracked change carries the reviewer's exact text (authoritative — that is what we write back
    to Notion), and SuperDocs still proposes it so the edit is validated by the engine and carries a
    change id to approve. A comment has no concrete edit, so SuperDocs' AI authors one from the
    reviewer's request — comments-as-intent, where the product does the changing; a question is
    never sent to the AI. Edits go out in batches of ``sections_per_op`` (one operation each), so a
    review with hundreds of edits stays bounded in cost and prompt size. A SuperDocs failure
    degrades gracefully: a reviewer's change is never lost.
    """
    existing_keys = {p.content_key() for p in round_.proposals}
    edits: list[MatchedEdit] = []
    comment_edits: list[MatchedEdit] = []
    questions: list[MatchedEdit] = []
    for edit in matched:
        total = len(edits) + len(comment_edits) + len(questions)
        if config.sample_size is not None and total >= config.sample_size:
            break
        if edit.is_text_change:
            edits.append(edit)
        elif edit.comment:
            # A directive ("tighten this") is an edit request for SuperDocs' AI to author. A
            # question ("which version?") is not — only the owner can answer it, so it must never
            # be handed to the AI (which could fabricate an answer). It becomes a Notion comment.
            (comment_edits if _is_edit_request(edit.comment) else questions).append(edit)

    specs = [EditSpec(ChangeOperation.REPLACE, e.original_text, e.proposed_text) for e in edits]
    intents = [IntentSpec(request=c.comment, passage=c.original_text) for c in comment_edits]
    proposed = _run_superdocs_review(round_, superdocs, specs, intents, config)
    used: set[int] = set()  # each returned proposal pairs with exactly one edit

    # Questions go straight to the owner as attributed Notion comments — never to the AI.
    for question in questions:
        _add_proposal(round_, existing_keys, _comment_proposal(question))

    # Tracked changes: reviewer text is authoritative; ride SuperDocs' change id for approve.
    for edit in edits:
        found = _match_proposal(proposed, edit.original_text, used)
        diff, job_id = found if found is not None else (None, "")
        _add_proposal(
            round_,
            existing_keys,
            ProposedChange(
                chunk_id=diff.chunk_id if diff else "",
                change_id=diff.change_id if diff else "",
                notion_block_id=edit.notion_block_id,
                notion_page_id=edit.notion_page_id,
                block_type=edit.block_type,
                cell_index=edit.cell_index,
                job_id=job_id,
                operation=ChangeOperation.REPLACE,
                old_html=f"<p>{escape(edit.original_text)}</p>",
                new_html=f"<p>{escape(edit.proposed_text)}</p>",
                source=ChangeSource.TRACKED_CHANGE,
                reviewer_name=edit.reviewer,
                reviewer_comment=edit.comment,
                links=_extract_links(edit.proposed_text),
            ),
        )

    # Directive comments: SuperDocs' AI authored the edit; if it declined, keep it as a note.
    for comment in comment_edits:
        found = _match_proposal(proposed, comment.original_text, used)
        if found is not None and found[0].new_html:
            diff, job_id = found
            new_text = plain_text_from_html(diff.new_html)
            _add_proposal(
                round_,
                existing_keys,
                ProposedChange(
                    chunk_id=diff.chunk_id,
                    change_id=diff.change_id,
                    notion_block_id=comment.notion_block_id,
                    notion_page_id=comment.notion_page_id,
                    block_type=comment.block_type,
                    job_id=job_id,
                    operation=ChangeOperation.REPLACE,
                    old_html=f"<p>{escape(comment.original_text)}</p>",
                    new_html=f"<p>{escape(new_text)}</p>",
                    source=ChangeSource.COMMENT_INTENT,
                    reviewer_name=comment.reviewer,
                    reviewer_comment=comment.comment,
                    ai_explanation=diff.ai_explanation,
                    links=_extract_links(new_text),
                ),
            )
        else:
            _add_proposal(round_, existing_keys, _comment_proposal(comment))


def _add_proposal(round_: ReviewRound, existing_keys: set[str], proposal: ProposedChange) -> None:
    if proposal.content_key() in existing_keys:
        return  # an identical change already exists (idempotent across re-runs)
    existing_keys.add(proposal.content_key())
    round_.proposals.append(proposal)


def _run_superdocs_review(
    round_: ReviewRound,
    superdocs: SuperDocsClient,
    edits: list[EditSpec],
    intents: list[IntentSpec],
    config: Config,
) -> list[tuple[ChunkDiff, str]]:
    """Propose one batch of edits in a single SuperDocs request; returns (proposal, job id) pairs.

    One operation covers up to 25 edited *sections* in a single request, and a session holds one
    pending proposal set at a time — so a batch is the unit of work here, and the caller (the
    graph) advances to the next batch only after this one has been gated and applied.
    """
    if not (edits or intents) or round_.ops_spent >= config.max_ops_per_round:
        if round_.ops_spent >= config.max_ops_per_round:
            _log.warning(
                "ops_ceiling_reached",
                extra={"round_id": round_.id, "ops_spent": round_.ops_spent},
            )
        return []
    parts = []
    if edits:
        parts.append(build_batch_instruction(edits))
    if intents:
        parts.append(build_intent_instruction(intents))
    job = _chat_with_retry(round_, superdocs, "\n\n".join(parts), config)
    if job is None:
        return []  # the batch failed; reviewer text is still authoritative, so nothing is lost
    if not job.chunk_diffs:
        _log.warning(
            "empty_proposal_set",
            extra={
                "round_id": round_.id,
                "job_id": job.job_id,
                "status": job.status.value,
                "asked_for": len(edits) + len(intents),
            },
        )
    # Count what this batch cost. The live API does not always return a usage block, and a budget
    # that only counts when the server volunteers a number is no budget at all — so fall back to
    # the documented rule: one operation per request that changed something (a request that errors
    # or changes nothing is not billed).
    if job.usage is not None and job.usage.ops_charged:
        round_.ops_spent += job.usage.ops_charged
    elif job.chunk_diffs:
        round_.ops_spent += 1
    return [(diff, job.job_id) for diff in job.chunk_diffs]


def _match_proposal(
    proposed: list[tuple[ChunkDiff, str]], original_text: str, used: set[int]
) -> tuple[ChunkDiff, str] | None:
    """Pair an edit with the proposal SuperDocs returned for it, across every batch.

    Exact as-sent text wins before containment, and each proposal is consumed once, so two edits
    with similar text can never collapse onto the same proposal.
    """
    target = _norm(original_text)
    if not target:
        return None
    for exact in (True, False):
        for index, (diff, job_id) in enumerate(proposed):
            if index in used:
                continue
            old = _norm(plain_text_from_html(diff.old_html))
            if not old:
                continue
            if (old == target) if exact else (target in old or old in target):
                used.add(index)
                return diff, job_id
    return None


def _chat_with_retry(
    round_: ReviewRound, superdocs: SuperDocsClient, message: str, config: Config
) -> Job | None:
    """Run the batched chat; re-submit a transient failure or an empty result, then give up.

    Two things count as worth re-submitting. The first is the explicit "engine at capacity"
    failure, whose own error text says to try again. The second is subtler and cost us a review
    once: a job that finishes reporting **no error and no proposals at all**. We only ever ask
    when we have concrete changes to propose, so nothing to show for it is a failure that simply
    forgot to say so — and taking it at face value silently downgrades every reviewer comment in
    the batch to a plain note. Retrying an empty set is free in the one way that matters: a
    request that changes nothing is not billed.

    Giving up is still safe: the reviewer's text is written to Notion authoritatively regardless,
    so this best-effort sync never blocks the review — it just may leave SuperDocs' copy unsynced.
    """
    job: Job | None = None
    delay = config.superdocs_backoff_base_s
    for attempt in range(config.superdocs_chat_retries + 1):
        try:
            job_id = superdocs.chat_async(session_id=round_.session_id, message=message)
            job = _poll_job(superdocs, job_id, config)
        except SuperDocsError as exc:
            _log.warning("superdocs_chat_failed", extra={"round_id": round_.id, "error": str(exc)})
            job = None
        if job is not None and not _worth_resubmitting(job):
            return job  # healthy result (or a non-transient failure we won't retry)
        if attempt < config.superdocs_chat_retries:
            _log.info(
                "superdocs_chat_retry",
                extra={
                    "round_id": round_.id,
                    "attempt": attempt + 1,
                    "error": job.error if job else None,
                    "why": "empty" if job is not None and not job.chunk_diffs else "failed",
                },
            )
            time.sleep(delay)
            delay *= 2
    return job


def _worth_resubmitting(job: Job) -> bool:
    """Whether this result is one to try again rather than accept."""
    if job.status == JobStatus.FAILED:
        return _is_transient(job.error)
    return not job.chunk_diffs  # finished, said nothing was wrong, proposed nothing


def _is_transient(error: str | None) -> bool:
    """Whether a failed job is the re-submittable "engine at capacity" kind."""
    if not error:
        return False
    lowered = error.lower()
    return "capacity" in lowered or "re-submit" in lowered or "did not start" in lowered


def _comment_proposal(edit: MatchedEdit) -> ProposedChange:
    return ProposedChange(
        chunk_id=edit.chunk_id or "",
        notion_block_id=edit.notion_block_id,
        notion_page_id=edit.notion_page_id,
        block_type=edit.block_type,
        operation=ChangeOperation.REPLACE,
        source=ChangeSource.COMMENT,
        reviewer_name=edit.reviewer,
        reviewer_comment=edit.comment,
    )


def _poll_job(superdocs: SuperDocsClient, job_id: str, config: Config) -> Job:
    """Poll an async job to a terminal state, within the configured time budget."""
    deadline = time.monotonic() + config.superdocs_poll_timeout_s
    while True:
        job = superdocs.get_job(job_id)
        if job.status in _TERMINAL:
            return job
        if time.monotonic() > deadline:
            raise TimeoutError(f"SuperDocs job {job_id} did not finish in time")
        time.sleep(config.superdocs_poll_interval_s)


def apply_decisions(
    round_: ReviewRound,
    decisions: list[dict[str, object]],
    notion: NotionClient,
    superdocs: SuperDocsClient,
    config: Config,
) -> None:
    """Record the human's item-by-item decisions, then apply the approved changes.

    The human gate is the review: it decides what lands. Each decision is relayed to SuperDocs'
    ``approve`` (the fourth contract call, which edits SuperDocs' own copy), and then written
    authoritatively onto the Notion block via Notion's API — the source of truth.
    """
    decision_by_id = {str(d["proposal_id"]): d for d in decisions}

    # 1. Record the human's decision on each change that is still awaiting one.
    #
    # A decision is read from Notion on every pass and a round can be resumed more than once, so
    # the same decision arrives repeatedly. It may only move a change that is still PENDING:
    # anything already acted on has reached its outcome, and re-recording it would send an applied
    # change back through the write — where it would trip its own drift guard, because the block
    # now holds the very text we wrote.
    for proposal in round_.proposals:
        decision = decision_by_id.get(proposal.id)
        if decision is None or proposal.status != ProposalStatus.PENDING:
            continue
        approved = bool(decision.get("approved"))
        proposal.status = ProposalStatus.APPROVED if approved else ProposalStatus.REJECTED

    # 2. Relay the decisions to SuperDocs' approve endpoint (the fourth contract call).
    _relay_to_superdocs_approve(round_, superdocs)

    # 3. Write each approved change back to Notion — idempotent, verified, attributed.
    round_.status = RoundStatus.APPLYING
    for proposal in round_.proposals:
        if proposal.status == ProposalStatus.APPROVED:
            _apply_one(round_, proposal, notion, config)

    failed = any(p.status == ProposalStatus.FAILED for p in round_.proposals)
    if failed:
        round_.status = RoundStatus.FAILED
    elif round_.pending():
        # Some changes in this batch have not been decided yet. The round is not finished: it goes
        # back to waiting so a later decision is still picked up, never stranded.
        round_.status = RoundStatus.AWAITING_APPROVAL
    else:
        round_.status = RoundStatus.COMPLETED
    # The completion summary is posted once the whole round finishes, not once per batch.


def _relay_to_superdocs_approve(round_: ReviewRound, superdocs: SuperDocsClient) -> None:
    """Relay the human's decisions to SuperDocs' ``approve`` — the fourth contract call.

    It applies each decision to SuperDocs' own copy of the document (keyed by ``change_id``). The
    authoritative write is still the Notion write-back, so a transport failure here is logged and
    the round proceeds — the source of truth is never left inconsistent.
    """
    # SuperDocs closes a job the moment it is approved: a second call for the rest of that job's
    # changes is refused with "Job is not awaiting approval (status: completed)". We get exactly
    # one call per job, so a job's decisions are held until every change it proposed has been
    # decided — spending the call early would strand the remainder, and the owner deciding a
    # queue over hours rather than all at once is the normal case, not the exception.
    undecided_jobs = {
        p.job_id for p in round_.proposals if p.status == ProposalStatus.PENDING and p.job_id
    }
    # "Decided" is anything past the gate, not only the two statuses a change holds for the instant
    # between the decision and the write. A change held back waiting for its siblings has already
    # been written to Notion by the time they arrive, so it is APPLIED — and looking only for
    # APPROVED would silently never relay it.
    decided = [
        p
        for p in round_.proposals
        if p.change_id
        and not p.relayed
        and p.job_id not in undecided_jobs
        and p.status != ProposalStatus.PENDING
    ]
    if not decided:
        return
    # Proposals from different batches belong to different jobs, so group by job and send one call
    # each — a change can only be approved against the job that proposed it. Each decision is
    # relayed exactly once, so an earlier batch's rejections are never re-sent.
    by_job: dict[str, list[ProposedChange]] = {}
    for proposal in decided:
        by_job.setdefault(proposal.job_id, []).append(proposal)

    for job_id, group in by_job.items():
        # What we relay is the human's decision, not what became of the write. A change the owner
        # approved that then hit a drift conflict was still approved; SuperDocs' own copy should
        # reflect the decision it was given.
        decisions = [
            ApprovalDecision(change_id=p.change_id, approved=p.status != ProposalStatus.REJECTED)
            for p in group
        ]
        try:
            result = superdocs.approve(
                session_id=round_.session_id, decisions=decisions, job_id=job_id
            )
            _log.info(
                "superdocs_approve",
                extra={"round_id": round_.id, "job_id": job_id, "applied": result.applied_count},
            )
        except SuperDocsError as exc:
            _log.warning(
                "superdocs_approve_failed", extra={"round_id": round_.id, "error": str(exc)}
            )
        for proposal in group:
            proposal.relayed = True  # decided once, sent once, whatever the outcome


def post_page_summaries(round_: ReviewRound, notion: NotionClient) -> None:
    """Close the loop on each page in the packet with its own outcome — a durable record.

    Posted once, when the whole round finishes, so a multi-batch review leaves one accurate
    summary per page instead of a premature "complete" after every batch.
    """
    fallback = round_.notion_page_id
    for page_id in round_.page_ids():
        on_page = [p for p in round_.proposals if (p.notion_page_id or fallback) == page_id]
        applied = sum(1 for p in on_page if p.status == ProposalStatus.APPLIED)
        rejected = sum(1 for p in on_page if p.status == ProposalStatus.REJECTED)
        conflicts = sum(1 for p in on_page if p.status == ProposalStatus.CONFLICT)
        if not (applied or rejected or conflicts):
            continue  # nothing happened to this page — leave it alone
        summary = f"Review round {round_.id} complete — {applied} applied, {rejected} rejected"
        if conflicts:
            summary += f", {conflicts} skipped (page changed since review)"
        # The page keeps a link back to the review round it came from: the round's queue, which
        # holds every change, who asked for it, and what became of it.
        note = [RichText(text=f"{summary}. ")]
        if round_.review_url:
            note.append(RichText(text="See the review round", href=round_.review_url))
        try:
            notion.create_comment(page_id=page_id, rich_text=note)
        except NotionError as exc:
            _log.warning(
                "summary_comment_failed",
                extra={"round_id": round_.id, "page_id": page_id, "error": str(exc)},
            )


def _apply_one(
    round_: ReviewRound, proposal: ProposedChange, notion: NotionClient, config: Config
) -> None:
    if proposal.status == ProposalStatus.APPLIED:
        return  # idempotent: already written on an earlier (interrupted) run
    try:
        if proposal.source in (ChangeSource.TRACKED_CHANGE, ChangeSource.COMMENT_INTENT):
            new_text = plain_text_from_html(proposal.new_html)
            # Size rail: refuse an edit whose text exceeds the cap. Untrusted markup, or a hostile
            # comment steering the AI, could otherwise balloon a block — surfaced, never written.
            if len(new_text) > config.max_edit_chars:
                proposal.status = ProposalStatus.FAILED
                proposal.error = (
                    f"edit exceeds the {config.max_edit_chars}-char size cap "
                    f"({len(new_text)} chars); not applied"
                )
                _log.warning(
                    "edit_too_large",
                    extra={
                        "round_id": round_.id,
                        "proposal_id": proposal.id,
                        "chars": len(new_text),
                    },
                )
                return
            # Drift guard: the reviewer marked up the text we sent. If the Notion block changed
            # since then (someone edited the page while it was out for review), overwriting would
            # silently discard that newer edit. Surface the conflict instead — never clobber.
            as_sent = plain_text_from_html(proposal.old_html)
            current = notion.retrieve_block(proposal.notion_block_id)
            # A table row holds no rich text of its own — its content is `cells` — so the same
            # read, compare, write, read-back has to speak that shape. Everything else about
            # the guarantee is identical: drift is surfaced, never clobbered, and the write is
            # confirmed by reading the block back.
            column = proposal.cell_index if proposal.block_type == "table_row" else None
            before = current.plain() if column is None else row_cells(current)[column]
            if _norm(before) != _norm(as_sent):
                proposal.status = ProposalStatus.CONFLICT
                proposal.error = "block changed in Notion since review; not overwritten"
                _log.warning(
                    "drift_conflict",
                    extra={"round_id": round_.id, "proposal_id": proposal.id},
                )
                return
            if column is not None:
                # Only the edited column is rewritten; every other cell goes back as it was.
                cells = row_cells(current)
                cells[column] = new_text
                notion.update_table_row(proposal.notion_block_id, cells=cells)
            else:
                # Surgical write-back: keep the block's untouched runs (bold, links, colour)
                # exactly as they were, rewriting only the span the reviewer actually changed.
                notion.update_block(
                    proposal.notion_block_id,
                    block_type=proposal.block_type,
                    rich_text=splice_plain_edit(current.rich_text, new_text),
                )
            landed = notion.retrieve_block(proposal.notion_block_id)
            after = landed.plain() if column is None else row_cells(landed)[column]
            if _norm(after) != _norm(new_text):
                proposal.status = ProposalStatus.FAILED
                proposal.error = "read-back mismatch: block did not reflect the change"
                return
            if proposal.source == ChangeSource.COMMENT_INTENT:
                note = (
                    f"Applied {proposal.reviewer_name}'s comment as an edit (review round "
                    f"{round_.id}): “{_clip(as_sent)}” → “{_clip(new_text)}”. "
                    f"Requested: “{_clip(proposal.reviewer_comment)}”."
                )
            else:
                note = (
                    f"Applied {proposal.reviewer_name}'s change (review round {round_.id}): "
                    f"“{_clip(as_sent)}” → “{_clip(new_text)}”"
                )
        else:
            note = (
                f"{proposal.reviewer_name} (review round {round_.id}): {proposal.reviewer_comment}"
            )
        notion.create_comment(
            block_id=proposal.notion_block_id,
            page_id=proposal.notion_page_id or round_.notion_page_id or None,
            rich_text=plain_text(note),
        )
        proposal.status = ProposalStatus.APPLIED
    except NotionError as exc:
        proposal.status = ProposalStatus.FAILED
        proposal.error = str(exc)
        _log.warning(
            "write_back_failed",
            extra={"round_id": round_.id, "proposal_id": proposal.id, "error": str(exc)},
        )
