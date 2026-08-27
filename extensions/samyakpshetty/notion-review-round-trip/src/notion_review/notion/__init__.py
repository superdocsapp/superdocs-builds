"""The Notion seam: typed block models, a client protocol matching Notion's REST API, an
in-memory fake for keyless tests, and a paginated tree fetch.

The fake models Notion's own block data structure — paragraphs, headings, toggles, callouts,
tables and inline databases — so the block-structure-preserving logic (blocks to HTML and the
range-by-range write-back) is exercised against the real shape without a token.
"""

from notion_review.notion.base import NotionClient
from notion_review.notion.fake import FakeNotionClient
from notion_review.notion.models import (
    Annotations,
    Block,
    ChildrenPage,
    Comment,
    Page,
    RichText,
    plain_text,
    rich,
)
from notion_review.notion.tree import fetch_block_tree, flatten

__all__ = [
    "Annotations",
    "Block",
    "ChildrenPage",
    "Comment",
    "FakeNotionClient",
    "NotionClient",
    "Page",
    "RichText",
    "fetch_block_tree",
    "flatten",
    "plain_text",
    "rich",
]
