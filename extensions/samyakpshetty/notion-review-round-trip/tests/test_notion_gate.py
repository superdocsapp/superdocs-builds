"""The approval gate driven from inside Notion: a queue the page owner decides in."""

from __future__ import annotations

from _docx_fixtures import CHANGE_AUTHOR, SECOND_REVIEWER, reviewed_docx, rival_reviewer_docx
from notion_review.config import Config
from notion_review.domain import ChangeSource, ProposalStatus, RoundStatus
from notion_review.notion import FakeNotionClient
from notion_review.notion.queue_schema import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED
from notion_review.roundtrip import InboundController, send_for_review
from notion_review.roundtrip.notion_gate import (
    announce_inline,
    await_decisions,
    publish_pending,
    read_decisions,
    read_inline_decisions,
    record_outcomes,
)
from notion_review.store import SQLiteStore
from notion_review.superdocs import FakeSuperDocsClient


def _setup() -> tuple[FakeNotionClient, SQLiteStore, InboundController, str]:
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    packet = send_for_review(notion=notion, superdocs=superdocs, store=store, page_id=page_id)
    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )
    return notion, store, controller, packet.round.id


def test_pending_changes_become_rows_the_owner_can_decide() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())

    added = publish_pending(gate.round, notion, store)

    assert added == len(gate.pending) == 2
    rows = notion.query_database(gate.round.queue_database_id)
    assert len(rows) == 2
    assert all(row.status == STATUS_PENDING for row in rows)  # nothing decided yet
    # Each row carries what the owner needs to decide, without leaving Notion.
    all_props = [notion.row_properties(row.page_id) for row in rows]
    assert all("Before" in p and "After" in p and "Kind" in p for p in all_props)
    assert any(CHANGE_AUTHOR in str(p["Reviewer"]) for p in all_props)  # attribution reaches Notion
    # The page tells the owner where to look.
    assert any("Review queue" in c.plain() for c in notion.comments_for(gate.round.notion_page_id))


def test_the_page_keeps_a_clickable_link_to_the_review_round() -> None:
    # The card asks that the page keep a link to the review round it came from. The round's queue
    # is that record — it holds every change, who asked for it, and what became of it — so the
    # page links to it, both when the review opens and when it closes.
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    publish_pending(gate.round, notion, store)

    round_ = store.get(round_id)
    assert round_ is not None
    assert round_.review_url  # a real Notion URL, not a fabricated anchor
    assert round_.queue_database_id in round_.review_url

    page_comments = notion.comments_for(round_.notion_page_id)
    linked = [run for c in page_comments for run in c.rich_text if run.href]
    assert any(run.href == round_.review_url for run in linked)  # clickable, on the page

    # And again when the round finishes, so the record survives the review.
    decisions = [{"proposal_id": p.id, "approved": True} for p in round_.pending()]
    final = controller.submit(round_id=round_id, decisions=decisions)
    closing = notion.comments_for(final.notion_page_id)[-1]
    assert "complete" in closing.plain()
    assert any(run.href == final.review_url for run in closing.rich_text if run.href)


def test_publishing_twice_does_not_duplicate_rows() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())

    publish_pending(gate.round, notion, store)
    again = publish_pending(gate.round, notion, store)  # e.g. after a restart

    assert again == 0
    assert len(notion.query_database(gate.round.queue_database_id)) == 2


def test_undecided_rows_yield_no_decisions() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    publish_pending(gate.round, notion, store)

    assert read_decisions(gate.round, notion) == []  # the owner has not acted


def test_owner_decisions_in_notion_drive_the_round_to_completion() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    publish_pending(gate.round, notion, store)
    aurora = next(e for e in gate.round.block_map if "Aurora ships in Q3" in e.original_text)
    approved_proposal = next(
        p for p in gate.round.pending() if p.notion_block_id == aurora.notion_block_id
    )
    other = next(p for p in gate.round.pending() if p.id != approved_proposal.id)

    # The page owner decides, in Notion.
    notion.set_row_status(approved_proposal.queue_row_id, STATUS_APPROVED)
    notion.set_row_status(other.queue_row_id, STATUS_REJECTED)

    decisions = await_decisions(gate.round, notion, poll_interval_s=0, timeout_s=1)
    assert len(decisions) == 2

    final = controller.submit(round_id=round_id, decisions=decisions)
    record_outcomes(final, notion, final.proposals)

    assert final.status == RoundStatus.COMPLETED
    assert "Q4" in notion.block_text(aurora.notion_block_id)  # the approved change landed
    applied = next(p for p in final.proposals if p.id == approved_proposal.id)
    rejected = next(p for p in final.proposals if p.id == other.id)
    assert applied.status == ProposalStatus.APPLIED
    assert rejected.status == ProposalStatus.REJECTED
    # The outcome is written back onto each row, so the queue shows what happened.
    assert "Applied" in str(notion.row_properties(applied.queue_row_id)["Outcome"])
    assert "Rejected" in str(notion.row_properties(rejected.queue_row_id)["Outcome"])


def test_each_change_is_announced_on_the_block_it_would_edit() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())

    posted = announce_inline(gate.round, notion, store)

    assert posted == len(gate.pending) == 2
    for proposal in gate.round.pending():
        # The proposal sits on the very block it would change, not at the bottom of the page.
        thread = notion.list_comments(proposal.notion_block_id)
        card = next(c for c in thread if c.discussion_id == proposal.discussion_id)
        assert proposal.reviewer_name in card.plain()
        assert "approve" in card.plain().lower()
    assert gate.round.bot_user_id  # we know our own voice, to tell a reply from our card


def test_the_comment_on_the_line_links_straight_to_its_queue_row() -> None:
    # Deciding should be a click, not a sentence: the comment carries a link to the row.
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    publish_pending(gate.round, notion, store)  # rows first, so their links exist
    announce_inline(gate.round, notion, store)

    proposal = gate.round.pending()[0]
    card = next(
        c
        for c in notion.list_comments(proposal.notion_block_id)
        if c.discussion_id == proposal.discussion_id
    )
    linked = [run for run in card.rich_text if run.href]
    assert linked and linked[0].href == proposal.queue_row_url
    assert "Approve or reject" in linked[0].text


def test_announcing_twice_does_not_repeat_the_comment() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())

    announce_inline(gate.round, notion, store)
    again = announce_inline(gate.round, notion, store)

    assert again == 0


def test_replying_approve_on_the_line_decides_the_change() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    announce_inline(gate.round, notion, store)
    first, second = gate.round.pending()

    notion.reply(first.discussion_id, "Approve — good catch.")
    notion.reply(second.discussion_id, "reject, we'll handle this separately")

    decisions = read_inline_decisions(gate.round, notion)

    assert {str(d["proposal_id"]): d["approved"] for d in decisions} == {
        first.id: True,
        second.id: False,
    }


def test_our_own_card_is_never_mistaken_for_a_reply() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    announce_inline(gate.round, notion, store)  # our card says "Reply approve or reject"

    assert read_inline_decisions(gate.round, notion) == []  # nobody has replied yet


def test_an_ambiguous_reply_is_left_undecided() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    announce_inline(gate.round, notion, store)
    proposal = gate.round.pending()[0]

    notion.reply(proposal.discussion_id, "hmm, let me think about this one")

    assert read_inline_decisions(gate.round, notion) == []  # never guessed


def test_a_partly_decided_queue_applies_only_what_was_decided() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    publish_pending(gate.round, notion, store)
    first = gate.round.pending()[0]
    notion.set_row_status(first.queue_row_id, STATUS_APPROVED)

    # Waiting stops at the deadline and returns what exists — the owner's work is not discarded.
    decisions = await_decisions(gate.round, notion, poll_interval_s=0, timeout_s=0)

    assert decisions == [{"proposal_id": first.id, "approved": True}]


def test_a_contested_line_says_so_on_every_row_including_the_one_queued_first() -> None:
    # The first reviewer's row is published before the second reviewer's copy even arrives, so
    # it has to be brought up to date — otherwise the collision is invisible on exactly the row
    # the owner is most likely to approve first.
    notion, store, controller, round_id = _setup()
    first = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    publish_pending(first.round, notion, store)
    announce_inline(first.round, notion, store)

    second = controller.start(round_id=round_id, docx_bytes=rival_reviewer_docx())
    publish_pending(second.round, notion, store)

    round_ = store.get(round_id)
    assert round_ is not None
    aurora_changes = [p for p in round_.pending() if p.source == ChangeSource.TRACKED_CHANGE]
    assert len(aurora_changes) == 2
    for proposal in aurora_changes:
        notes = notion.row_text(proposal.queue_row_id, "Notes")
        assert "rewrote this line" in notes
        rival = SECOND_REVIEWER if proposal.reviewer_name == CHANGE_AUTHOR else CHANGE_AUTHOR
        assert rival in notes  # and it names who it competes with


def test_an_uncontested_change_is_never_labelled_as_competing() -> None:
    notion, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    publish_pending(gate.round, notion, store)

    round_ = store.get(round_id)
    assert round_ is not None
    for proposal in round_.pending():
        assert "rewrote this line" not in notion.row_text(proposal.queue_row_id, "Notes")
