"""The approval gate, driven from inside Notion.

Approval is an *operation*, not a screen: ``InboundController`` exposes it, and any surface can
drive it. This driver puts that surface where the page owner already works — no second app, no
extra login, no hosted frontend — and offers each change two ways, because the two answer
different needs:

* **On the line.** Every pending change is commented onto the exact block it would edit, so the
  owner sees Notion's comment marker where the change actually is, reads what is proposed, and
  replies "approve" or "reject" without going anywhere. A reply that says neither is left
  undecided rather than guessed at, and our own proposal card is never mistaken for an answer.
* **In a queue.** The same changes are rows in a review-queue database on the page, with a Status
  field, so a review with dozens of changes can be sorted, filtered, and decided in bulk — and the
  outcome of each one is written back onto its row.

Comments are metadata, so neither surface inserts or removes a single block: the page itself is
only ever touched by an approved change. Decisions are collected by polling — Notion's webhooks are
deliberately not relied on — which is fine for a review measured in hours or days and keeps the
integration to one moving part.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from notion_review.domain import ChangeSource, ProposedChange, ReviewRound
from notion_review.logging import get_logger
from notion_review.notion.base import NotionClient, NotionError
from notion_review.notion.models import RichText
from notion_review.notion.queue_schema import (
    STATUS_PENDING,
    competing_note,
    decision_from_status,
    notes_properties,
    outcome_properties,
    queue_properties,
    row_properties,
    summarize,
)
from notion_review.roundtrip.inbound import plain_text_from_html
from notion_review.store import Store

_log = get_logger("notion_review.notion_gate")


def ensure_queue(round_: ReviewRound, notion: NotionClient) -> str:
    """Create the round's review queue on the page, once; returns the database id.

    The queue is also the round's durable record: it lives on the page, holds every change with
    who asked for it and what became of it, and its URL is the link the page keeps back to the
    review round it came from.
    """
    if round_.queue_database_id:
        return round_.queue_database_id
    database = notion.create_database(
        parent_page_id=round_.notion_page_id,
        title=f"Review queue · round {round_.id}",
        properties=queue_properties(),
    )
    round_.queue_database_id = database.id
    round_.review_url = database.url
    _log.info("queue_created", extra={"round_id": round_.id, "database_id": database.id})
    return database.id


def notify_waiting(round_: ReviewRound, notion: NotionClient) -> None:
    """Tell the page owner that changes are waiting, with a link straight to them."""
    try:
        notion.create_comment(
            page_id=round_.notion_page_id,
            rich_text=[
                RichText(text=f"Review round {round_.id}: changes are waiting for you in "),
                RichText(text=f"Review queue · round {round_.id}", href=round_.review_url or None),
                RichText(text=" on this page. Set each row's Status to Approved or Rejected."),
            ],
        )
    except NotionError as exc:  # the queue still exists; the notice is a courtesy
        _log.warning("queue_notice_failed", extra={"round_id": round_.id, "error": str(exc)})


def rivals_for(round_: ReviewRound, proposal: ProposedChange) -> list[str]:
    """The other reviewers whose pending change rewrites this same block."""
    others = [
        other
        for other in round_.contested().get(proposal.notion_block_id, [])
        if other.id != proposal.id
    ]
    return list(dict.fromkeys(other.reviewer_name for other in others))


def publish_pending(round_: ReviewRound, notion: NotionClient, store: Store) -> int:
    """Add a row for every pending change that does not have one yet. Returns rows added.

    The row ids are persisted here rather than left to the caller: they are the only link between
    a proposal and the owner's decision, so losing them would strand the queue.

    A later reviewer's copy can turn an already-queued change into a contested one, so rows
    published earlier are brought up to date here too — otherwise the first reviewer's row would
    be the only one that never mentions the collision.
    """
    database_id = ensure_queue(round_, notion)
    first_publish = not any(p.queue_row_id for p in round_.proposals)
    added = 0
    for proposal in round_.pending():
        rivals = rivals_for(round_, proposal)
        if proposal.queue_row_id:
            _flag_competing(round_, proposal, rivals, notion)
            continue  # already queued (idempotent across restarts and re-publishes)
        row = notion.create_row(
            database_id=database_id,
            properties=row_properties(
                proposal,
                before=plain_text_from_html(proposal.old_html),
                after=plain_text_from_html(proposal.new_html),
                rivals=rivals,
            ),
        )
        proposal.queue_row_id = row.page_id
        proposal.queue_row_url = row.url
        proposal.competing_notified = bool(rivals)
        added += 1
    store.save(round_)
    if added and first_publish:
        notify_waiting(round_, notion)  # once, when the first changes arrive to be decided
    _log.info("queue_published", extra={"round_id": round_.id, "rows": added})
    return added


def _flag_competing(
    round_: ReviewRound, proposal: ProposedChange, rivals: list[str], notion: NotionClient
) -> None:
    """Tell an already-published row that a later reviewer has now rewritten the same line."""
    if not rivals or proposal.competing_notified:
        return
    try:
        notion.update_row(
            page_id=proposal.queue_row_id, properties=notes_properties(proposal, rivals)
        )
    except NotionError as exc:
        _log.warning(
            "competing_notice_failed",
            extra={"round_id": round_.id, "row": proposal.queue_row_id, "error": str(exc)},
        )
        return
    proposal.competing_notified = True
    _log.info(
        "competing_changes",
        extra={
            "round_id": round_.id,
            "block": proposal.notion_block_id,
            "reviewers": len(rivals) + 1,
        },
    )


_APPROVE_WORDS = frozenset({"approve", "approved", "approving", "yes", "lgtm", "ok", "okay", "👍"})
_REJECT_WORDS = frozenset({"reject", "rejected", "rejecting", "no", "decline", "declined", "👎"})


def announce_inline(round_: ReviewRound, notion: NotionClient, store: Store) -> int:
    """Comment each pending change onto the block it would edit. Returns comments posted.

    The queue database is good for deciding many changes at once, but it sits away from the text.
    This puts the proposal where the change actually is: the owner sees Notion's comment marker on
    that exact line, reads what is proposed, and can simply reply "approve" or "reject" — or open
    the linked queue row if they would rather use the Status field. Two ways to decide, one gate.
    """
    posted = 0
    for proposal in round_.pending():
        if proposal.discussion_id:
            continue  # already announced (idempotent across restarts)
        before = plain_text_from_html(proposal.old_html)
        after = plain_text_from_html(proposal.new_html)
        if proposal.source == ChangeSource.COMMENT:
            body = (
                f"{proposal.reviewer_name} asked, in review round {round_.id}: "
                f"“{proposal.reviewer_comment}” · "
            )
        else:
            authored = (
                " (written by SuperDocs from the reviewer's comment)"
                if (proposal.source == ChangeSource.COMMENT_INTENT)
                else ""
            )
            body = f"{proposal.reviewer_name} proposes{authored}: {summarize(before, after)} · "
        contest = competing_note(rivals_for(round_, proposal))
        if contest:
            body = f"{body}{contest} · "
        # One click to decide: the comment links straight to this change's row in the queue, where
        # Status is a two-click select. Replying "approve" or "reject" here works too, for anyone
        # who would rather answer in the thread than open the row.
        card = [RichText(text=body)]
        if proposal.queue_row_url:
            card.append(RichText(text="Approve or reject →", href=proposal.queue_row_url))
        else:
            card.append(RichText(text="Reply approve or reject."))
        try:
            comment = notion.create_comment(
                block_id=proposal.notion_block_id,
                page_id=proposal.notion_page_id or round_.notion_page_id or None,
                rich_text=card,
            )
        except NotionError as exc:
            _log.warning(
                "inline_announce_failed",
                extra={"round_id": round_.id, "proposal_id": proposal.id, "error": str(exc)},
            )
            continue
        proposal.discussion_id = comment.discussion_id
        if not round_.bot_user_id:
            round_.bot_user_id = comment.author  # so a human reply is told from our own card
        posted += 1
    store.save(round_)
    _log.info("inline_announced", extra={"round_id": round_.id, "comments": posted})
    return posted


def _decision_in(text: str) -> bool | None:
    """Read a reply as a decision. Anything unrecognised is left undecided, never guessed."""
    words = {word.strip(".,!;:()").lower() for word in text.split()}
    if words & _APPROVE_WORDS:
        return True
    if words & _REJECT_WORDS:
        return False
    return None


def read_inline_decisions(round_: ReviewRound, notion: NotionClient) -> list[dict[str, object]]:
    """Decisions the owner replied with, in the comment thread on each changed block."""
    decisions: list[dict[str, object]] = []
    for proposal in round_.pending():
        if not proposal.discussion_id:
            continue
        try:
            thread = notion.list_comments(proposal.notion_block_id)
        except NotionError as exc:
            _log.warning(
                "inline_read_failed",
                extra={"round_id": round_.id, "block": proposal.notion_block_id, "error": str(exc)},
            )
            continue
        for comment in thread:
            if comment.discussion_id != proposal.discussion_id:
                continue
            if comment.author == round_.bot_user_id:
                continue  # our own proposal card, not a reply
            decided = _decision_in(comment.plain())
            if decided is not None:
                decisions.append({"proposal_id": proposal.id, "approved": decided})
                break
    return decisions


def read_decisions(round_: ReviewRound, notion: NotionClient) -> list[dict[str, object]]:
    """The decisions the owner has made so far, as the controller's decision payloads."""
    if not round_.queue_database_id:
        return []
    rows = notion.query_database(round_.queue_database_id)
    status_by_row = {row.page_id: row.status for row in rows}
    decisions: list[dict[str, object]] = []
    for proposal in round_.pending():
        if not proposal.queue_row_id:
            continue
        approved = decision_from_status(status_by_row.get(proposal.queue_row_id, STATUS_PENDING))
        if approved is not None:
            decisions.append({"proposal_id": proposal.id, "approved": approved})
    return decisions


def await_decisions(
    round_: ReviewRound,
    notion: NotionClient,
    *,
    poll_interval_s: float = 15.0,
    timeout_s: float = 86_400.0,
    on_wait: Callable[[int, int], None] | None = None,
) -> list[dict[str, object]]:
    """Poll the queue until every pending change has been decided, or the deadline passes.

    Returns whatever decisions exist when it stops, so a partially-reviewed round still applies
    what the owner approved rather than discarding their work.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        decisions = read_decisions(round_, notion)
        outstanding = len(round_.pending()) - len(decisions)
        if outstanding <= 0 or time.monotonic() >= deadline:
            return decisions
        if on_wait is not None:
            on_wait(len(decisions), len(round_.pending()))
        time.sleep(poll_interval_s)


def record_outcomes(
    round_: ReviewRound, notion: NotionClient, decided: list[ProposedChange]
) -> None:
    """Write what became of each decided change back onto its queue row."""
    for proposal in decided:
        if not proposal.queue_row_id:
            continue
        try:
            notion.update_row(
                page_id=proposal.queue_row_id, properties=outcome_properties(proposal)
            )
        except NotionError as exc:
            _log.warning(
                "queue_outcome_failed",
                extra={"round_id": round_.id, "row": proposal.queue_row_id, "error": str(exc)},
            )
