"""The Notion client protocol — the exact operations the round-trip needs, and no more.

Method shapes mirror Notion's REST API so the live client is a thin mapping and the fake is a
faithful stand-in: retrieve a page, page through a block's children, update one block's text,
and attach a comment. Write-back is deliberately per-block (``update_block``) — we only ever
touch the blocks a reviewer changed, so everything else provably stays as it was.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from notion_review.notion.models import (
    Block,
    ChildrenPage,
    Comment,
    DatabaseRef,
    Page,
    QueueRow,
    RichText,
)


class NotionError(Exception):
    """A Notion operation failed (missing object, invalid request, transport error)."""


class NotionNotFoundError(NotionError):
    """The requested page or block does not exist / is not shared with the integration."""


@runtime_checkable
class NotionClient(Protocol):
    def retrieve_page(self, page_id: str) -> Page: ...

    def retrieve_block(self, block_id: str) -> Block:
        """Fetch a single block — used to verify a write-back actually landed."""
        ...

    def list_block_children(
        self, block_id: str, *, start_cursor: str | None = None, page_size: int = 100
    ) -> ChildrenPage:
        """One page of children — the API is paginated at 100, callers must follow the cursor."""
        ...

    def update_block(self, block_id: str, *, block_type: str, rich_text: list[RichText]) -> Block:
        """Replace one block's rich text in place. Only changed blocks are ever passed here."""
        ...

    def update_table_row(self, block_id: str, *, cells: list[str]) -> Block:
        """Replace one table row's cells. A row has no rich text, so it needs its own call."""
        ...

    def create_comment(
        self,
        *,
        rich_text: list[RichText],
        page_id: str | None = None,
        block_id: str | None = None,
    ) -> Comment:
        """Attach a comment to a page or block — how reviewer attribution reaches Notion."""
        ...

    def list_comments(self, block_id: str) -> list[Comment]:
        """Every comment on a block, threads included — this is how a reply is read back."""
        ...

    # -- the in-Notion review queue: where the page owner approves each change ---------------
    def create_database(
        self, *, parent_page_id: str, title: str, properties: dict[str, Any]
    ) -> DatabaseRef:
        """Create the review-queue database under the page; returns its id and URL."""
        ...

    def search_databases(self, query: str) -> list[DatabaseRef]:
        """Every database shared with this integration whose title matches ``query``.

        Notion's search only ever returns what a person has explicitly shared with the connection,
        which is what lets the integration *find* its request boards instead of being told their
        ids. The match is fuzzy, so callers filter by exact title themselves.
        """
        ...

    def create_row(self, *, database_id: str, properties: dict[str, Any]) -> QueueRow:
        """Add one proposed change to the queue as a row the owner can decide on."""
        ...

    def query_database(self, database_id: str) -> list[QueueRow]:
        """Read every row of the queue, following pagination — this is how decisions come back."""
        ...

    def update_row(self, *, page_id: str, properties: dict[str, Any]) -> None:
        """Write a row's properties — used to record the outcome once a change is applied."""
        ...

    # -- files on a row: the review document out, and the reviewer's copy back ----------------
    def upload_file(self, *, content: bytes, filename: str, content_type: str) -> str:
        """Upload a file to Notion; returns the id to attach it to a ``files`` property with.

        Two calls in Notion's API — create the upload, then send the bytes — and the id is only
        useful until it is attached, so callers attach it straight away via ``update_row``.
        """
        ...

    def download_file(self, url: str) -> bytes:
        """Fetch a file Notion hosts, from the signed URL a ``files`` property hands back."""
        ...
