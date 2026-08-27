from __future__ import annotations

from notion_review.domain import (
    BlockMapEntry,
    ChangeOperation,
    ProposalStatus,
    ProposedChange,
    ReviewRound,
    RoundStatus,
)


def _change(**kw: object) -> ProposedChange:
    base: dict[str, object] = {
        "chunk_id": "chunk_1",
        "notion_block_id": "blk_1",
        "operation": ChangeOperation.REPLACE,
        "new_html": "<p>Hello world</p>",
    }
    base.update(kw)
    return ProposedChange(**base)  # type: ignore[arg-type]


def test_content_key_is_whitespace_insensitive() -> None:
    a = _change(new_html="<p>Hello   world</p>")
    b = _change(new_html="<p>Hello world</p>\n")
    assert a.content_key() == b.content_key()


def test_content_key_separates_distinct_changes() -> None:
    assert _change(new_html="<p>A</p>").content_key() != _change(new_html="<p>B</p>").content_key()
    assert (
        _change(notion_block_id="blk_1").content_key()
        != _change(notion_block_id="blk_2").content_key()
    )
    assert (
        _change(operation=ChangeOperation.REPLACE).content_key()
        != _change(operation=ChangeOperation.DELETE).content_key()
    )


def test_ids_are_prefixed() -> None:
    rnd = ReviewRound(notion_page_id="page_1")
    assert rnd.id.startswith("round_")
    assert rnd.session_id.startswith("sess_")
    assert _change().id.startswith("chg_")


def test_round_helpers_filter_by_status() -> None:
    rnd = ReviewRound(
        notion_page_id="page_1",
        block_map=[
            BlockMapEntry(
                notion_block_id="blk_1", block_type="paragraph", anchor="a1", chunk_id="chunk_1"
            )
        ],
        proposals=[
            _change(status=ProposalStatus.PENDING),
            _change(status=ProposalStatus.APPROVED),
            _change(status=ProposalStatus.REJECTED),
        ],
    )
    assert len(rnd.pending()) == 1
    assert len(rnd.approved()) == 1
    assert rnd.block_for_chunk("chunk_1") is not None
    assert rnd.block_for_chunk("missing") is None


def test_touch_advances_updated_at() -> None:
    rnd = ReviewRound(notion_page_id="page_1")
    before = rnd.updated_at
    rnd.touch()
    assert rnd.updated_at >= before
    assert rnd.status == RoundStatus.CREATED
