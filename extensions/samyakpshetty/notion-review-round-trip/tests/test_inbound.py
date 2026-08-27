"""The inbound half: match markup → propose → human gate → apply, end to end on fakes."""

from __future__ import annotations

from _docx_fixtures import (
    CHANGE_AUTHOR,
    COMMENT_AUTHOR,
    COMMENTED_PARA,
    DUP_MIDDLE,
    DUP_TEXT,
    INTENT_COMMENT,
    INTENT_PARA,
    LINK_ORIGINAL,
    OTHER_PARA_PROPOSED,
    PACKET_P1_ORIGINAL,
    PACKET_P1_PROPOSED,
    PACKET_P2_ORIGINAL,
    PACKET_P2_PROPOSED,
    PARA_ORIGINAL,
    QUESTION_COMMENT,
    QUESTION_PARA,
    SECOND_REVIEWER,
    comment_intent_docx,
    duplicate_second_edited_docx,
    link_and_script_docx,
    packet_review_docx,
    question_comment_docx,
    reviewed_docx,
    rival_reviewer_docx,
    second_reviewer_docx,
    two_tracked_changes_docx,
    unchanged_docx,
)
from notion_review.config import Config
from notion_review.docx_markup import parse_docx
from notion_review.domain import ChangeSource, ProposalStatus, RoundStatus
from notion_review.notion import FakeNotionClient
from notion_review.notion.html import blocks_to_html
from notion_review.notion.models import Annotations, RichText, plain_text, row_cells
from notion_review.notion.tree import fetch_block_tree
from notion_review.roundtrip import (
    InboundController,
    ReviewGate,
    match_edits,
    send_for_review,
    send_packet_for_review,
)
from notion_review.roundtrip.checkpoint import open_checkpointer
from notion_review.store import SQLiteStore
from notion_review.superdocs import FakeSuperDocsClient


def _outbound(
    notion: FakeNotionClient, page_id: str, superdocs: FakeSuperDocsClient, store: SQLiteStore
):
    return send_for_review(notion=notion, superdocs=superdocs, store=store, page_id=page_id)


def _setup() -> tuple[FakeNotionClient, FakeSuperDocsClient, SQLiteStore, InboundController, str]:
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    packet = _outbound(notion, page_id, superdocs, store)
    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )
    return notion, superdocs, store, controller, packet.round.id


# -- unit: matching -----------------------------------------------------------
def test_match_edits_ties_changes_to_blocks() -> None:
    notion, page_id = FakeNotionClient.build_sample()
    _, block_map = blocks_to_html(fetch_block_tree(notion, page_id))
    markup = parse_docx(reviewed_docx())
    matched, unmatched = match_edits(markup, block_map)
    assert unmatched == []
    assert len(matched) == 2
    text_change = next(m for m in matched if m.is_text_change)
    assert "Q4" in text_change.proposed_text and text_change.reviewer == CHANGE_AUTHOR
    comment_edit = next(m for m in matched if not m.is_text_change)
    assert comment_edit.comment and comment_edit.reviewer == COMMENT_AUTHOR


def test_edit_to_the_second_of_two_identical_blocks_lands_on_the_second() -> None:
    # A page with two byte-identical paragraphs; the reviewer edits the second. Matching by text
    # alone would collapse both onto the first block — positional matching must not.
    notion = FakeNotionClient()
    page_id = notion.new_page("Duplicates")
    first = notion.add(page_id, "paragraph", DUP_TEXT)
    notion.add(page_id, "paragraph", DUP_MIDDLE)
    second = notion.add(page_id, "paragraph", DUP_TEXT)

    _, block_map = blocks_to_html(fetch_block_tree(notion, page_id))
    markup = parse_docx(duplicate_second_edited_docx())
    matched, unmatched = match_edits(markup, block_map)

    assert unmatched == []
    assert len(matched) == 1
    assert matched[0].notion_block_id == second  # the second copy, never the first
    assert matched[0].notion_block_id != first


def test_more_same_text_changes_than_blocks_are_surfaced_not_guessed() -> None:
    # One block, but two identical-text paragraphs both edited: the extra change has no block to
    # land on and must be surfaced, never applied to a guessed target.
    notion = FakeNotionClient()
    page_id = notion.new_page("Ambiguous")
    notion.add(page_id, "paragraph", DUP_TEXT)  # a single block with this text
    notion.add(page_id, "paragraph", DUP_MIDDLE)
    _, block_map = blocks_to_html(fetch_block_tree(notion, page_id))

    markup = parse_docx(duplicate_second_edited_docx())  # two paragraphs carry DUP_TEXT
    matched, unmatched = match_edits(markup, block_map)

    assert len(matched) == 0  # the sole edit is on the second copy, which has no block
    assert unmatched == [DUP_TEXT]


def test_comment_becomes_an_ai_authored_edit_gated_and_written_to_notion() -> None:
    # A directive comment (not a question) is turned into a concrete edit by SuperDocs' AI,
    # proposed through our gate, and written to Notion on approval — comments-as-intent.
    notion = FakeNotionClient()
    page_id = notion.new_page("Spec")
    block = notion.add(page_id, "paragraph", INTENT_PARA)
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )

    gate = controller.start(round_id=round_id, docx_bytes=comment_intent_docx())
    intent = next(p for p in gate.pending if p.source == ChangeSource.COMMENT_INTENT)
    assert intent.reviewer_comment == INTENT_COMMENT
    assert intent.ai_explanation  # SuperDocs explained the edit it authored
    assert "[revised]" in intent.new_html  # the AI (fake) rewrote the passage

    final = controller.submit(
        round_id=round_id, decisions=[{"proposal_id": intent.id, "approved": True}]
    )
    assert final.status == RoundStatus.COMPLETED
    assert "[revised]" in notion.block_text(block)  # the AI-authored edit landed on the block


def test_a_reviewer_question_stays_a_comment_for_the_owner_never_an_ai_edit() -> None:
    # A question only the owner can answer must never be handed to the AI (it could fabricate an
    # answer). It is surfaced as an attributed Notion comment; the block text is left untouched.
    notion = FakeNotionClient()
    page_id = notion.new_page("Spec")
    block = notion.add(page_id, "paragraph", QUESTION_PARA)
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )

    gate = controller.start(round_id=round_id, docx_bytes=question_comment_docx())
    assert len(gate.pending) == 1
    assert gate.pending[0].source == ChangeSource.COMMENT  # a note, not an AI-authored edit
    assert superdocs.chat_calls() == 0  # the question was never sent to SuperDocs

    final = controller.submit(
        round_id=round_id, decisions=[{"proposal_id": gate.pending[0].id, "approved": True}]
    )
    assert final.status == RoundStatus.COMPLETED
    assert notion.block_text(block) == QUESTION_PARA  # untouched — no fabricated answer
    assert any(QUESTION_COMMENT in c.plain() for c in notion.comments_for(block))


def test_many_edits_are_split_into_batches_of_sections_per_op() -> None:
    # A review with more edits than one operation covers must go out in batches — one operation
    # each — not as a single unbounded request. Every edit still lands.
    from _docx_fixtures import build_docx

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    notion = FakeNotionClient()
    page_id = notion.new_page("Many edits")
    blocks = [notion.add(page_id, "paragraph", f"Paragraph number {i} is here.") for i in range(5)]

    paras = "".join(
        f"<w:p><w:r><w:t>Paragraph number {i} is </w:t></w:r>"
        f'<w:del w:id="{i * 2}" w:author="Dana Reviewer" w:date="2026-08-13T10:00:00Z">'
        f"<w:r><w:delText>here.</w:delText></w:r></w:del>"
        f'<w:ins w:id="{i * 2 + 1}" w:author="Dana Reviewer" w:date="2026-08-13T10:00:00Z">'
        f"<w:r><w:t>revised.</w:t></w:r></w:ins></w:p>"
        for i in range(5)
    )
    markup = build_docx(
        f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{paras}</w:body></w:document>'
    )

    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    controller = InboundController(
        notion=notion,
        superdocs=superdocs,
        store=store,
        config=Config(sections_per_op=2),  # 5 edits -> 3 batches
    )

    # A SuperDocs session holds one pending proposal set at a time, so batches are gated in turn:
    # propose <=2 -> approve -> apply (frees the session) -> propose the next.
    gate = controller.start(round_id=round_id, docx_bytes=markup)
    rounds = 0
    while gate.pending:
        assert len(gate.pending) <= 2  # never more than one batch awaits approval
        rounds += 1
        final = controller.submit(
            round_id=round_id,
            decisions=[{"proposal_id": p.id, "approved": True} for p in gate.pending],
        )
        gate = ReviewGate(round=final, pending=final.pending())

    assert rounds == 3  # ceil(5 / 2) batches, each gated on its own
    assert superdocs.chat_calls() == 3  # one request per batch
    assert superdocs.monthly_used() == 3  # one operation per batch, not per edit
    assert all("revised." in notion.block_text(b) for b in blocks)  # every edit landed


def test_extract_links_flags_urls_and_dangerous_schemes() -> None:
    from notion_review.roundtrip.inbound import _extract_links

    links = _extract_links("Ping https://ok.example.com or click javascript:steal() now")
    assert "https://ok.example.com" in links
    assert any("dangerous scheme" in link and "javascript:" in link for link in links)
    assert _extract_links("no links here") == []


def test_an_edits_links_are_surfaced_and_script_content_lands_inert() -> None:
    notion = FakeNotionClient()
    page_id = notion.new_page("Spec")
    block = notion.add(page_id, "paragraph", LINK_ORIGINAL)
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )

    gate = controller.start(round_id=round_id, docx_bytes=link_and_script_docx())
    assert any("evil.example.com" in link for link in gate.pending[0].links)  # surfaced at the gate

    controller.submit(
        round_id=round_id, decisions=[{"proposal_id": gate.pending[0].id, "approved": True}]
    )
    landed = notion.block_text(block)
    assert "<script>" in landed  # written as literal text — a tag, not executable structure
    assert "evil.example.com" in landed


def test_an_oversized_edit_is_refused_at_the_write_boundary() -> None:
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    round0 = store.get(round_id)
    assert round0 is not None
    aurora = next(e for e in round0.block_map if "Aurora ships in Q3" in e.original_text)
    tiny_cap = Config(max_edit_chars=5)  # the Q4 edit is far longer than 5 chars
    controller = InboundController(notion=notion, superdocs=superdocs, store=store, config=tiny_cap)

    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    text_change = next(p for p in gate.pending if p.source == ChangeSource.TRACKED_CHANGE)
    final = controller.submit(
        round_id=round_id, decisions=[{"proposal_id": text_change.id, "approved": True}]
    )

    refused = next(p for p in final.proposals if p.id == text_change.id)
    assert refused.status == ProposalStatus.FAILED and "size cap" in (refused.error or "")
    assert "Q4" not in notion.block_text(aurora.notion_block_id)  # never written


def test_drift_in_notion_is_a_conflict_not_a_silent_overwrite() -> None:
    notion, _, store, controller, round_id = _setup()
    round0 = store.get(round_id)
    assert round0 is not None
    aurora = next(e for e in round0.block_map if "Aurora ships in Q3" in e.original_text)

    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    # Someone edits the page in Notion while it is out for review.
    drifted = "Aurora ships in Q3 — but the scope changed materially after this went out."
    notion.update_block(
        aurora.notion_block_id, block_type="paragraph", rich_text=plain_text(drifted)
    )

    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    final = controller.submit(round_id=round_id, decisions=decisions)

    text_change = next(p for p in final.proposals if p.source == ChangeSource.TRACKED_CHANGE)
    assert text_change.status == ProposalStatus.CONFLICT
    # The newer Notion edit is preserved; the stale reviewer change never landed.
    assert notion.block_text(aurora.notion_block_id) == drifted
    assert "Q4" not in notion.block_text(aurora.notion_block_id)


def test_reproposing_a_persisted_round_never_respends_ops() -> None:
    notion, superdocs, store, controller, round_id = _setup()
    controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    after_first = superdocs.chat_calls()
    assert after_first >= 1

    # Simulate a crash/restart: a brand-new controller (fresh graph + checkpointer) re-enters the
    # same persisted round. The already-proposed changes must not be sent to SuperDocs again.
    controller2 = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )
    gate = controller2.start(round_id=round_id, docx_bytes=reviewed_docx())

    assert superdocs.chat_calls() == after_first  # zero ops re-spent
    assert len(gate.pending) == 2  # the same proposals are still awaiting approval


def test_a_transient_superdocs_capacity_failure_is_retried_then_succeeds() -> None:
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient(fail_chats=2)  # first two chats fail "at capacity"
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    fast = Config(superdocs_backoff_base_s=0.001)  # don't actually sleep in the test
    controller = InboundController(notion=notion, superdocs=superdocs, store=store, config=fast)

    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())

    assert superdocs.chat_calls() == 3  # two transient failures re-submitted, the third ran
    assert superdocs.monthly_used() == 1  # only the successful run was billed
    assert len(gate.pending) == 2  # the round proposed regardless of the retries


def test_a_killed_review_resumes_at_the_gate_from_a_durable_checkpoint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore(str(tmp_path / "state.db"))
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    ckpt = str(tmp_path / "graph.ckpt")

    # First run: propose to the gate, then "crash" — drop the controller entirely.
    first = InboundController(
        notion=notion,
        superdocs=superdocs,
        store=store,
        config=Config.from_env({}),
        checkpointer=open_checkpointer(ckpt),
    )
    gate = first.start(round_id=round_id, docx_bytes=reviewed_docx())
    assert len(gate.pending) == 2
    calls = superdocs.chat_calls()

    # Restart: a fresh controller on the same checkpoint file resumes and applies the decisions,
    # without re-running propose (no SuperDocs op is re-spent).
    resumed = InboundController(
        notion=notion,
        superdocs=superdocs,
        store=store,
        config=Config.from_env({}),
        checkpointer=open_checkpointer(ckpt),
    )
    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    final = resumed.submit(round_id=round_id, decisions=decisions)

    assert final.status == RoundStatus.COMPLETED
    assert superdocs.chat_calls() == calls
    assert all(p.status == ProposalStatus.APPLIED for p in final.proposals)


def test_multi_page_packet_fans_each_change_back_to_its_own_page() -> None:
    notion = FakeNotionClient()
    page1 = notion.new_page("Alpha spec")
    block1 = notion.add(page1, "paragraph", PACKET_P1_ORIGINAL)
    page2 = notion.new_page("Beta spec")
    block2 = notion.add(page2, "paragraph", PACKET_P2_ORIGINAL)
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()

    packet = send_packet_for_review(
        notion=notion, superdocs=superdocs, store=store, page_ids=[page1, page2]
    )
    assert {e.notion_page_id for e in packet.round.block_map} == {page1, page2}

    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )
    gate = controller.start(round_id=packet.round.id, docx_bytes=packet_review_docx())
    assert len(gate.pending) == 2
    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    final = controller.submit(round_id=packet.round.id, decisions=decisions)

    assert final.status == RoundStatus.COMPLETED
    # Both edits went to SuperDocs in a single batched chat — one operation, not one per change.
    assert superdocs.chat_calls() == 1
    assert superdocs.monthly_used() == 1
    assert notion.block_text(block1) == PACKET_P1_PROPOSED  # page 1's edit on page 1's block
    assert notion.block_text(block2) == PACKET_P2_PROPOSED  # page 2's edit on page 2's block
    # Attribution reached the right page, and each page carries its own completion summary.
    assert any(CHANGE_AUTHOR in c.plain() for c in notion.comments_for(block1))
    assert any(COMMENT_AUTHOR in c.plain() for c in notion.comments_for(block2))
    assert any("complete" in c.plain() for c in notion.comments_for(page1))
    assert any("complete" in c.plain() for c in notion.comments_for(page2))


# -- the golden round-trip ----------------------------------------------------
def test_full_round_trip_applies_approved_changes_and_preserves_the_rest() -> None:
    notion, _, store, controller, round_id = _setup()
    round0 = store.get(round_id)
    assert round0 is not None
    aurora = next(e for e in round0.block_map if "Aurora ships in Q3" in e.original_text)
    ingestion = next(e for e in round0.block_map if "ingestion service" in e.original_text)
    overview = next(e for e in round0.block_map if e.original_text == "Overview")
    before = {e.notion_block_id: notion.block_text(e.notion_block_id) for e in round0.block_map}

    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    assert gate.round.status == RoundStatus.AWAITING_APPROVAL
    assert len(gate.pending) == 2

    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    final = controller.submit(round_id=round_id, decisions=decisions)

    assert final.status == RoundStatus.COMPLETED
    # The approved text change landed on the exact block.
    assert "Q4" in notion.block_text(aurora.notion_block_id)
    assert "Q3" not in notion.block_text(aurora.notion_block_id)
    # Everything else is byte-for-byte what it was.
    assert notion.block_text(overview.notion_block_id) == before[overview.notion_block_id]
    # Attribution reached Notion, for both the edit and the comment.
    assert any(
        CHANGE_AUTHOR in c.plain() and final.id in c.plain()
        for c in notion.comments_for(aurora.notion_block_id)
    )
    assert any(COMMENT_AUTHOR in c.plain() for c in notion.comments_for(ingestion.notion_block_id))
    assert all(p.status == ProposalStatus.APPLIED for p in final.proposals)


def test_round_reports_what_it_spent_and_where_the_time_went() -> None:
    _, _, _, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    final = controller.submit(round_id=round_id, decisions=decisions)

    assert final.ops_spent == 1  # one text edit is one op; the comment costs nothing
    assert {"propose", "apply"} <= set(final.stage_timings_ms)
    assert all(ms >= 0 for ms in final.stage_timings_ms.values())
    assert "SuperDocs op(s)" in final.cost_summary()


def test_a_word_change_preserves_the_rest_of_the_blocks_formatting() -> None:
    notion, _, store, controller, round_id = _setup()
    round0 = store.get(round_id)
    assert round0 is not None
    aurora = next(e for e in round0.block_map if "Aurora ships in Q3" in e.original_text)

    # Give the block real styling whose plain text still matches what was sent for review.
    notion.update_block(
        aurora.notion_block_id,
        block_type="paragraph",
        rich_text=[
            RichText(text="Aurora ships in Q3 and targets "),
            RichText(text="mid-market teams", annotations=Annotations(bold=True)),
            RichText(text=" migrating off spreadsheets."),
        ],
    )

    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    controller.submit(round_id=round_id, decisions=decisions)

    landed = notion.retrieve_block(aurora.notion_block_id)
    assert "Q4" in landed.plain() and "Q3" not in landed.plain()  # the edit applied
    bold = [r for r in landed.rich_text if r.annotations.bold]
    assert len(bold) == 1 and bold[0].text == "mid-market teams"  # styling survived surgically


def test_rejected_change_is_never_written() -> None:
    notion, _, store, controller, round_id = _setup()
    round0 = store.get(round_id)
    assert round0 is not None
    aurora = next(e for e in round0.block_map if "Aurora ships in Q3" in e.original_text)

    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    text_change = next(p for p in gate.pending if p.source == ChangeSource.TRACKED_CHANGE)
    decisions = [{"proposal_id": text_change.id, "approved": False}]
    final = controller.submit(round_id=round_id, decisions=decisions)

    assert "Q3" in notion.block_text(aurora.notion_block_id)  # unchanged
    rejected = next(p for p in final.proposals if p.id == text_change.id)
    assert rejected.status == ProposalStatus.REJECTED


def test_no_changes_completes_without_a_gate() -> None:
    _, _, _, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=unchanged_docx("Overview"))
    assert gate.pending == []
    assert gate.round.status == RoundStatus.COMPLETED  # nothing to review → done


def test_quota_limit_does_not_discard_reviewer_changes() -> None:
    # SuperDocs is out of operations. The metered chat is a best-effort sync, not a gate — the
    # reviewer's changes are authoritative, so they must still be proposed and remain appliable.
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient(monthly_limit=0)
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )

    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    assert gate.round.status == RoundStatus.AWAITING_APPROVAL
    assert len(gate.pending) == 2  # nothing lost to the quota limit

    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    final = controller.submit(round_id=round_id, decisions=decisions)
    assert final.status == RoundStatus.COMPLETED  # applies authoritatively regardless


def test_read_back_mismatch_marks_the_change_failed() -> None:
    # A Notion client whose write silently does not land — the read-back must catch it.
    class DroppingNotion(FakeNotionClient):
        def update_block(self, block_id, *, block_type, rich_text):  # type: ignore[no-untyped-def]
            return self.retrieve_block(block_id)  # pretend success, change nothing

    notion = DroppingNotion()
    page_id = notion.new_page("Spec")
    notion.add(page_id, "paragraph", PARA_ORIGINAL)
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )

    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    final = controller.submit(round_id=round_id, decisions=decisions)

    assert final.status == RoundStatus.FAILED
    failed = [p for p in final.proposals if p.status == ProposalStatus.FAILED]
    assert failed and "read-back" in (failed[0].error or "")


def test_a_second_reviewers_copy_is_taken_in_alongside_the_first() -> None:
    # Every reviewer marks up their own copy, so the same round takes in several returned files.
    _, _, store, controller, round_id = _setup()

    controller.start(round_id=round_id, docx_bytes=reviewed_docx(), filename="from-dana.docx")
    gate = controller.start(
        round_id=round_id, docx_bytes=second_reviewer_docx(), filename="from-priya.docx"
    )

    reviewers = {p.reviewer_name for p in gate.pending}
    assert CHANGE_AUTHOR in reviewers  # the first reviewer's tracked change
    assert SECOND_REVIEWER in reviewers  # the second reviewer's, which used to be dropped
    proposed = {p.new_html for p in gate.pending}
    assert any(OTHER_PARA_PROPOSED in html for html in proposed)
    round_ = store.get(round_id)
    assert round_ is not None
    assert [s.filename for s in round_.submissions] == ["from-dana.docx", "from-priya.docx"]


def test_the_same_returned_file_twice_costs_nothing_and_adds_nothing() -> None:
    # A channel that re-delivers, or a restart mid-tick, must not re-spend or duplicate.
    _, superdocs, store, controller, round_id = _setup()

    first = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    calls = superdocs.chat_calls()
    again = controller.start(round_id=round_id, docx_bytes=reviewed_docx())

    assert superdocs.chat_calls() == calls  # zero ops re-spent
    assert len(again.pending) == len(first.pending)
    round_ = store.get(round_id)
    assert round_ is not None and len(round_.submissions) == 1


def test_changes_from_two_reviewers_are_approved_together_and_both_land() -> None:
    notion, _, store, controller, round_id = _setup()
    controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    gate = controller.start(round_id=round_id, docx_bytes=second_reviewer_docx())
    round_ = store.get(round_id)
    assert round_ is not None
    aurora = next(e for e in round_.block_map if PARA_ORIGINAL in e.original_text)
    postgres = next(e for e in round_.block_map if COMMENTED_PARA in e.original_text)

    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    final = controller.submit(round_id=round_id, decisions=decisions)

    # Each reviewer's change landed on its own block: two threads, one round, one decision pass.
    assert "Q4" in notion.block_text(aurora.notion_block_id)
    assert notion.block_text(postgres.notion_block_id) == OTHER_PARA_PROPOSED
    assert final.status == RoundStatus.COMPLETED


def test_two_reviewers_rewriting_one_line_are_flagged_as_competing_before_the_decision() -> None:
    _, _, store, controller, round_id = _setup()
    controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    gate = controller.start(round_id=round_id, docx_bytes=rival_reviewer_docx())
    round_ = store.get(round_id)
    assert round_ is not None
    aurora = next(e for e in round_.block_map if PARA_ORIGINAL in e.original_text)

    contested = round_.contested()

    assert list(contested) == [aurora.notion_block_id]
    assert len(contested[aurora.notion_block_id]) == 2
    assert {p.reviewer_name for p in contested[aurora.notion_block_id]} == {
        CHANGE_AUTHOR,
        SECOND_REVIEWER,
    }
    # And approving both is safe: the first lands, the second is refused by the drift guard
    # rather than overwriting it.
    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    final = controller.submit(round_id=round_id, decisions=decisions)
    on_block = [p for p in final.proposals if p.notion_block_id == aurora.notion_block_id]
    assert sorted(p.status.value for p in on_block) == ["applied", "conflict"]


def test_resubmitting_a_decision_leaves_an_applied_change_applied() -> None:
    # Decisions are read from Notion on every pass, so the same one comes back repeatedly. A
    # change already written must not go through the write a second time: the block now holds
    # the text we wrote, so it would trip its own drift guard and undo a good outcome.
    notion, _, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=reviewed_docx())
    round_ = store.get(round_id)
    assert round_ is not None
    aurora = next(e for e in round_.block_map if PARA_ORIGINAL in e.original_text)
    decisions = [{"proposal_id": p.id, "approved": True} for p in gate.pending]
    controller.submit(round_id=round_id, decisions=decisions)

    final = controller.submit(round_id=round_id, decisions=decisions)  # the very same decisions

    assert [p.status.value for p in final.proposals] == ["applied", "applied"]
    assert "Q4" in notion.block_text(aurora.notion_block_id)


def test_a_chat_that_proposes_nothing_at_all_is_re_submitted() -> None:
    # Seen live: a job finishes reporting no error and returns an empty proposal set. Taken at
    # face value it silently downgrades every reviewer comment in the batch to a plain note, so
    # it is re-submitted rather than believed.
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient(empty_chats=2)  # first two chats come back empty and healthy
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    fast = Config(superdocs_backoff_base_s=0.001)
    controller = InboundController(notion=notion, superdocs=superdocs, store=store, config=fast)

    gate = controller.start(round_id=round_id, docx_bytes=comment_intent_docx())

    assert superdocs.chat_calls() == 3  # two empty results re-submitted, the third proposed
    authored = [p for p in gate.pending if p.source == ChangeSource.COMMENT_INTENT]
    assert authored, "the reviewer's comment should have become an AI-authored edit"
    assert authored[0].change_id  # and it carries a change id to approve against


def test_an_empty_proposal_set_that_never_recovers_still_keeps_the_reviewer_comment() -> None:
    # The retry is bounded. When it is exhausted the comment is kept as an attributed note —
    # degraded, but a reviewer's words are never dropped.
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient(empty_chats=99)
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    fast = Config(superdocs_backoff_base_s=0.001)
    controller = InboundController(notion=notion, superdocs=superdocs, store=store, config=fast)

    gate = controller.start(round_id=round_id, docx_bytes=comment_intent_docx())

    kept = [p for p in gate.pending if p.source == ChangeSource.COMMENT]
    assert kept and INTENT_COMMENT in kept[0].reviewer_comment


def test_a_jobs_decisions_are_relayed_once_all_of_them_are_in() -> None:
    # SuperDocs closes a job the moment it is approved, and refuses a second call for the rest of
    # its changes. Deciding a queue over hours is the normal case, so the call is held until every
    # change from that job has been decided — spending it early would strand the remainder.
    _, _, store, controller, round_id = _setup()
    gate = controller.start(round_id=round_id, docx_bytes=two_tracked_changes_docx())
    with_change_id = [p for p in gate.pending if p.change_id]
    assert len(with_change_id) == 2  # both proposed by the same chat job
    assert len({p.job_id for p in with_change_id}) == 1

    # Only some of the job's changes decided: nothing may be relayed yet.
    controller.submit(
        round_id=round_id,
        decisions=[{"proposal_id": with_change_id[0].id, "approved": True}],
    )
    partial = store.get(round_id)
    assert partial is not None
    assert not any(p.relayed for p in partial.proposals)

    # Now the rest — one call, and it must not raise the live 400.
    final = controller.submit(
        round_id=round_id,
        decisions=[{"proposal_id": p.id, "approved": True} for p in partial.pending()],
    )

    assert all(p.relayed for p in final.proposals if p.change_id)
    assert final.status == RoundStatus.COMPLETED


def test_a_reviewers_edit_to_a_table_cell_lands_on_that_cell_and_no_other() -> None:
    """A table row is one Notion block but several cells, and Word gives each its own paragraph.

    The whole point of this build is that the structure survives the round trip, so an edit a
    reviewer makes inside a table cell has to reach that cell — and leave every other cell as it
    was. Three separate things had to be true for that: the row needs its own chunk (one
    ``<table>`` per row, not one table of rows), the returned cell paragraph has to match its
    column, and the write-back has to speak ``cells`` rather than ``rich_text``, because a row
    carries no rich text of its own.
    """
    from _docx_fixtures import build_docx

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    notion, page_id = FakeNotionClient.build_sample()
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()
    _outbound(notion, page_id, superdocs, store)
    round_id = store.list_ids()[0]
    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )

    # The reviewer retypes one price cell in Word; the row's other cell is untouched.
    doc = (
        f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body><w:tbl><w:tr>'
        f"<w:tc><w:p><w:r><w:t>Pro</w:t></w:r></w:p></w:tc>"
        f"<w:tc><w:p>"
        f'<w:del w:id="1" w:author="Dana Reviewer" w:date="2026-08-27T10:00:00Z">'
        f"<w:r><w:delText>$99/mo</w:delText></w:r></w:del>"
        f'<w:ins w:id="2" w:author="Dana Reviewer" w:date="2026-08-27T10:00:00Z">'
        f"<w:r><w:t>$129/mo</w:t></w:r></w:ins>"
        f"</w:p></w:tc></w:tr></w:tbl></w:body></w:document>"
    )
    gate = controller.start(round_id=round_id, docx_bytes=build_docx(doc))
    assert len(gate.pending) == 1, "the cell edit was not matched to its row"
    proposal = gate.pending[0]
    assert proposal.block_type == "table_row"
    assert proposal.cell_index == 1  # the price column, not the plan column

    final = controller.submit(
        round_id=round_id, decisions=[{"proposal_id": proposal.id, "approved": True}]
    )
    assert final.status == RoundStatus.COMPLETED
    row = notion.retrieve_block(proposal.notion_block_id)
    assert row_cells(row) == ["Pro", "$129/mo"]  # the edited cell changed; its neighbour did not
