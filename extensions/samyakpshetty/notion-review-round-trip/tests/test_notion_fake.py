from __future__ import annotations

from notion_review.notion import (
    FakeNotionClient,
    NotionClient,
    fetch_block_tree,
    flatten,
    plain_text,
)
from notion_review.notion.base import NotionNotFoundError


def test_fake_satisfies_the_protocol() -> None:
    assert isinstance(FakeNotionClient(), NotionClient)


def test_sample_tree_preserves_structure_and_nesting() -> None:
    client, page_id = FakeNotionClient.build_sample()
    tree = fetch_block_tree(client, page_id)
    types = [b.type for b in tree]
    assert types == ["heading_1", "paragraph", "toggle", "callout", "table"]

    toggle = next(b for b in tree if b.type == "toggle")
    assert toggle.has_children
    assert [c.type for c in toggle.children] == ["paragraph"]

    table = next(b for b in tree if b.type == "table")
    assert [c.type for c in table.children] == ["table_row", "table_row"]

    callout = next(b for b in tree if b.type == "callout")
    assert callout.meta["icon"] == "💡"  # type-specific metadata survives the fetch


def test_pagination_is_followed() -> None:
    client = FakeNotionClient()
    page_id = client.new_page("Long page")
    for i in range(250):
        client.add(page_id, "paragraph", f"Paragraph {i}")
    # page_size below the total forces the cursor to be followed.
    tree = fetch_block_tree_paginated(client, page_id, page_size=100)
    assert len(tree) == 250
    assert tree[0].plain() == "Paragraph 0"
    assert tree[-1].plain() == "Paragraph 249"


def fetch_block_tree_paginated(client: NotionClient, page_id: str, *, page_size: int) -> list:
    # Exercise list_block_children pagination directly with a small page size.
    out = []
    cursor = None
    while True:
        page = client.list_block_children(page_id, start_cursor=cursor, page_size=page_size)
        out.extend(page.results)
        if not page.has_more:
            return out
        cursor = page.next_cursor


def test_update_block_changes_only_that_block() -> None:
    client, page_id = FakeNotionClient.build_sample()
    tree = fetch_block_tree(client, page_id)
    para = next(b for b in tree if b.type == "paragraph")
    others_before = {b.id: b.plain() for b in flatten(tree) if b.id != para.id}

    client.update_block(
        para.id, block_type="paragraph", rich_text=plain_text("Aurora ships in Q4, not Q3.")
    )

    assert client.block_text(para.id) == "Aurora ships in Q4, not Q3."
    after = fetch_block_tree(client, page_id)
    others_after = {b.id: b.plain() for b in flatten(after) if b.id != para.id}
    assert others_after == others_before  # nothing else moved


def test_comment_carries_attribution() -> None:
    client, page_id = FakeNotionClient.build_sample()
    block_id = fetch_block_tree(client, page_id)[1].id
    client.create_comment(
        rich_text=plain_text("Applied Dana's change from Review Round 1."), block_id=block_id
    )
    comments = client.comments_for(block_id)
    assert len(comments) == 1
    assert "Dana" in comments[0].plain()
    assert comments[0].author == FakeNotionClient.BOT_ID  # authored by the integration, not a human
    assert comments[0].discussion_id  # a thread the owner can reply into


def test_missing_page_raises_typed_error() -> None:
    client = FakeNotionClient()
    try:
        client.retrieve_page("page_does_not_exist")
    except NotionNotFoundError as exc:
        assert "not found" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("expected NotionNotFoundError")
