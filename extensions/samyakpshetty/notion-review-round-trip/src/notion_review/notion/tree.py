"""Fetch a page's full block tree, following pagination and nesting.

Notion returns children 100 at a time and only one level deep, so reconstructing the tree is
the caller's job. We follow every cursor and recurse into container blocks (toggles, callouts,
tables), with a depth guard so a malformed/cyclic tree can never spin forever.
"""

from __future__ import annotations

from notion_review.notion.base import NotionClient, NotionError
from notion_review.notion.models import Block

_MAX_DEPTH = 50  # Notion's own nesting ceiling is well under this; the guard is defensive.


def fetch_block_tree(client: NotionClient, page_id: str) -> list[Block]:
    """Return the page's top-level blocks, each with its ``children`` populated recursively."""
    return _children(client, page_id, depth=0)


def _children(client: NotionClient, block_id: str, *, depth: int) -> list[Block]:
    if depth >= _MAX_DEPTH:
        raise NotionError(f"block nesting exceeded {_MAX_DEPTH} levels at {block_id}")
    out: list[Block] = []
    cursor: str | None = None
    while True:
        page = client.list_block_children(block_id, start_cursor=cursor)
        for block in page.results:
            if block.has_children:
                block.children = _children(client, block.id, depth=depth + 1)
            out.append(block)
        if not page.has_more:
            return out
        cursor = page.next_cursor


def flatten(blocks: list[Block]) -> list[Block]:
    """Depth-first flatten of a block tree, parents before children."""
    out: list[Block] = []
    for block in blocks:
        out.append(block)
        out.extend(flatten(block.children))
    return out
