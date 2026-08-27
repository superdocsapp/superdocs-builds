"""An in-memory Notion stand-in: a real block tree with pagination, updates, and comments.

It stores blocks flat with a parent→children index (as Notion does internally) and paginates
``list_block_children`` for real, so the tree-fetch and write-back logic are exercised against
Notion's actual shape without a token. ``build_sample`` produces a page with the structures the
assigned build must preserve: a heading, a paragraph, a toggle with a nested child, a callout,
and a table with rows.
"""

from __future__ import annotations

from notion_review.notion.base import NotionNotFoundError
from notion_review.notion.models import (
    Block,
    ChildrenPage,
    Comment,
    DatabaseRef,
    Page,
    QueueRow,
    RichText,
    plain_text,
)

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class FakeNotionClient:
    """In-memory implementation of :class:`~notion_review.notion.base.NotionClient`."""

    BOT_ID = "bot-superdocs-review-bridge"  # what our own comments are authored by

    def __init__(self) -> None:
        self._pages: dict[str, Page] = {}
        self._blocks: dict[str, Block] = {}  # stored without children resolved
        self._children: dict[str, list[str]] = {}  # parent id -> ordered child ids
        self._comments: list[Comment] = []
        self._databases: dict[str, list[str]] = {}  # database id -> ordered row ids
        self._database_titles: dict[str, str] = {}
        self._rows: dict[str, dict[str, object]] = {}  # row id -> Notion property payloads
        self._uploads: dict[str, bytes] = {}  # upload id -> file contents
        self._upload_names: dict[str, str] = {}
        self._counter = 0

    # -- construction helpers (tests / demo build the tree with these) ---------
    def _next(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter:04d}"

    def _next_uuid(self) -> str:
        """A Notion-shaped id. Real ids are UUIDs, and callers parse them out of pasted URLs."""
        self._counter += 1
        n = self._counter
        return f"{n:08x}-0000-4000-8000-{n:012x}"

    def new_page(self, title: str) -> str:
        page_id = self._next_uuid()
        self._pages[page_id] = Page(id=page_id, title=title, url=f"https://notion.so/{page_id}")
        self._children[page_id] = []
        return page_id

    def add(
        self,
        parent_id: str,
        block_type: str,
        text: str = "",
        *,
        meta: dict[str, object] | None = None,
    ) -> str:
        """Append a block under ``parent_id``; returns its id (use it as a parent to nest)."""
        block_id = self._next("block")
        self._blocks[block_id] = Block(
            id=block_id,
            type=block_type,
            rich_text=plain_text(text) if text else [],
            meta=meta or {},
        )
        self._children.setdefault(parent_id, []).append(block_id)
        self._children.setdefault(block_id, [])
        return block_id

    # -- the client contract ---------------------------------------------------
    def retrieve_page(self, page_id: str) -> Page:
        try:
            return self._pages[page_id]
        except KeyError:
            raise NotionNotFoundError(f"page not found: {page_id}") from None

    def retrieve_block(self, block_id: str) -> Block:
        if block_id not in self._blocks:
            raise NotionNotFoundError(f"block not found: {block_id}")
        return self._snapshot(block_id)

    def list_block_children(
        self, block_id: str, *, start_cursor: str | None = None, page_size: int = 100
    ) -> ChildrenPage:
        child_ids = self._children.get(block_id, [])
        start = int(start_cursor) if start_cursor else 0
        window = child_ids[start : start + page_size]
        results = [self._snapshot(cid) for cid in window]
        end = start + page_size
        has_more = end < len(child_ids)
        return ChildrenPage(
            results=results,
            next_cursor=str(end) if has_more else None,
            has_more=has_more,
        )

    def update_block(self, block_id: str, *, block_type: str, rich_text: list[RichText]) -> Block:
        block = self._blocks.get(block_id)
        if block is None:
            raise NotionNotFoundError(f"block not found: {block_id}")
        block.rich_text = list(rich_text)
        return self._snapshot(block_id)

    def update_table_row(self, block_id: str, *, cells: list[str]) -> Block:
        block = self._blocks.get(block_id)
        if block is None:
            raise NotionNotFoundError(f"block not found: {block_id}")
        # Stored the way the live client reports them: one list of runs per cell.
        block.meta["cells"] = [[text] for text in cells]
        return self._snapshot(block_id)

    def create_comment(
        self,
        *,
        rich_text: list[RichText],
        page_id: str | None = None,
        block_id: str | None = None,
    ) -> Comment:
        parent = block_id or page_id
        if parent is None:
            raise NotionNotFoundError("create_comment requires page_id or block_id")
        comment = Comment(
            id=self._next("comment"),
            parent_id=parent,
            rich_text=list(rich_text),
            author=self.BOT_ID,
            created_time="2026-01-01T00:00:00Z",
            discussion_id=self._next("discussion"),
        )
        self._comments.append(comment)
        return comment

    def list_comments(self, block_id: str) -> list[Comment]:
        return [c for c in self._comments if c.parent_id == block_id]

    def reply(self, discussion_id: str, text: str, *, author: str = "human-owner") -> Comment:
        """Stand in for a person replying in a Notion comment thread (tests and the demo)."""
        parent = next((c.parent_id for c in self._comments if c.discussion_id == discussion_id), "")
        reply = Comment(
            id=self._next("comment"),
            parent_id=parent,
            rich_text=plain_text(text),
            author=author,
            created_time="2026-01-01T00:00:00Z",
            discussion_id=discussion_id,
        )
        self._comments.append(reply)
        return reply

    # -- the in-Notion review queue --------------------------------------------
    def create_database(
        self, *, parent_page_id: str, title: str, properties: dict[str, object]
    ) -> DatabaseRef:
        database_id = self._next("db")
        self._databases[database_id] = []
        self._database_titles[database_id] = title
        return DatabaseRef(id=database_id, url=f"https://notion.so/{database_id}", title=title)

    def archive_database(self, database_id: str) -> None:
        """Stand in for somebody archiving a board in Notion (tests and the demo).

        Notion's search keeps listing an archived database until its index catches up, so
        this leaves the title in place and makes only the reads fail — which is what the
        live service actually sees.
        """
        self._databases.pop(database_id, None)

    def search_databases(self, query: str) -> list[DatabaseRef]:
        """Match any word of the query, because Notion's search is looser than a substring.

        Checked against the live API: searching for "Review requests" also returns every
        "Review queue · round …" database, on the strength of the shared word "Review". A fake
        that matched on substring would be *stricter* than the real thing and would quietly hide
        the reason callers have to filter by exact title.
        """
        words = {word for word in query.strip().lower().split() if word}
        return [
            DatabaseRef(id=db_id, url=f"https://notion.so/{db_id}", title=title)
            for db_id, title in self._database_titles.items()
            if words & set(title.lower().split())
        ]

    def create_row(self, *, database_id: str, properties: dict[str, object]) -> QueueRow:
        if database_id not in self._databases:
            raise NotionNotFoundError(f"database not found: {database_id}")
        page_id = self._next("row")
        self._rows[page_id] = dict(properties)
        self._databases[database_id].append(page_id)
        return QueueRow(
            page_id=page_id,
            status=self._status_of(page_id),
            url=f"https://notion.so/{page_id}",
            properties=dict(self._rows[page_id]),
        )

    def query_database(self, database_id: str) -> list[QueueRow]:
        if database_id not in self._databases:
            raise NotionNotFoundError(f"database not found: {database_id}")
        return [
            QueueRow(
                page_id=pid,
                status=self._status_of(pid),
                url=f"https://notion.so/{pid}",
                properties=dict(self._rows[pid]),
            )
            for pid in self._databases[database_id]
        ]

    def update_row(self, *, page_id: str, properties: dict[str, object]) -> None:
        if page_id not in self._rows:
            raise NotionNotFoundError(f"row not found: {page_id}")
        self._rows[page_id].update(
            {name: self._settle(value) for name, value in properties.items()}
        )

    def _settle(self, value: object) -> object:
        """Store a written property in the shape a *reader* gets back from Notion.

        Notion does not hand back what you wrote: an attached ``file_upload`` comes back as a
        hosted file with a URL, and a rich-text run comes back with the ``plain_text`` Notion
        derives from it. A fake that stored the write verbatim would agree with the live service
        on the way in and disagree on the way out — which is exactly the kind of difference that
        passes every test and then fails in production.
        """
        if isinstance(value, dict):
            for field in ("rich_text", "title"):
                runs = value.get(field)
                if isinstance(runs, list):
                    return {**value, field: [self._settle_run(run) for run in runs]}
        if not (isinstance(value, dict) and isinstance(value.get("files"), list)):
            return value
        settled: list[dict[str, object]] = []
        for entry in value["files"]:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "file_upload":
                reference = entry.get("file_upload")
                upload_id = reference.get("id", "") if isinstance(reference, dict) else ""
                settled.append(
                    {
                        "name": entry.get("name") or self._upload_names.get(str(upload_id), ""),
                        "type": "file",
                        "file": {"url": self.file_url(str(upload_id))},
                    }
                )
            else:
                settled.append(entry)
        return {**value, "files": settled}

    @staticmethod
    def _settle_run(run: object) -> object:
        """Fill in the ``plain_text`` Notion derives from a written rich-text run."""
        if not isinstance(run, dict) or "plain_text" in run:
            return run
        text = run.get("text")
        content = text.get("content", "") if isinstance(text, dict) else ""
        return {**run, "plain_text": content}

    def _status_of(self, page_id: str) -> str:
        prop = self._rows[page_id].get("Status")
        if isinstance(prop, dict):
            select = prop.get("select")
            if isinstance(select, dict):
                return str(select.get("name", ""))
        return ""

    def set_row_status(self, page_id: str, status: str) -> None:
        """Stand in for the page owner deciding a change in Notion (tests and the demo)."""
        self.update_row(page_id=page_id, properties={"Status": {"select": {"name": status}}})

    # -- files on a row --------------------------------------------------------
    def upload_file(self, *, content: bytes, filename: str, content_type: str) -> str:
        """Hold the bytes and hand back an id, exactly as the two-step live upload does."""
        upload_id = self._next("upload")
        self._uploads[upload_id] = content
        self._upload_names[upload_id] = filename
        return upload_id

    def download_file(self, url: str) -> bytes:
        """Serve a file back from its URL, the way a signed Notion URL does."""
        upload_id = url.rsplit("/", 1)[-1]
        if upload_id not in self._uploads:
            raise NotionNotFoundError(f"file not found: {url}")
        return self._uploads[upload_id]

    def file_url(self, upload_id: str) -> str:
        """The URL a ``files`` property reports for an uploaded file."""
        return f"https://files.notion.so/{upload_id}"

    def attach_file(self, page_id: str, *, property_name: str, content: bytes, name: str) -> None:
        """Stand in for a person dragging their marked-up copy onto a row (tests and the demo)."""
        upload_id = self.upload_file(content=content, filename=name, content_type=_DOCX_MIME)
        existing = self._rows[page_id].get(property_name)
        files: list[dict[str, object]] = []
        if isinstance(existing, dict) and isinstance(existing.get("files"), list):
            files = list(existing["files"])
        files.append({"name": name, "type": "file", "file": {"url": self.file_url(upload_id)}})
        self.update_row(page_id=page_id, properties={property_name: {"files": files}})

    def row_properties(self, page_id: str) -> dict[str, object]:
        return dict(self._rows[page_id])

    def row_text(self, page_id: str, name: str) -> str:
        """Read one rich-text (or title) property back as plain text, the way a reader sees it."""
        prop = self._rows[page_id].get(name)
        if not isinstance(prop, dict):
            return ""
        runs = prop.get("rich_text") or prop.get("title") or []
        if not isinstance(runs, list):
            return ""
        return "".join(str(run.get("text", {}).get("content", "")) for run in runs)

    # -- introspection for tests -----------------------------------------------
    def _snapshot(self, block_id: str) -> Block:
        """Return a copy of a stored block with ``has_children`` set, children left unresolved."""
        block = self._blocks[block_id]
        return block.model_copy(
            update={"has_children": bool(self._children.get(block_id)), "children": []}
        )

    def block_text(self, block_id: str) -> str:
        return self._blocks[block_id].plain()

    def comments_for(self, parent_id: str) -> list[Comment]:
        return [c for c in self._comments if c.parent_id == parent_id]

    @classmethod
    def build_sample(cls) -> tuple[FakeNotionClient, str]:
        """A page exercising the structures the build must preserve across the round-trip."""
        client = cls()
        page_id = client.new_page("Product Spec: Project Aurora")
        client.add(page_id, "heading_1", "Overview")
        client.add(
            page_id,
            "paragraph",
            "Aurora ships in Q3 and targets mid-market teams migrating off spreadsheets.",
        )
        toggle_id = client.add(page_id, "toggle", "Implementation details")
        client.add(
            toggle_id,
            "paragraph",
            "The ingestion service runs on a single Postgres instance behind a queue.",
        )
        client.add(
            page_id,
            "callout",
            "Pricing in this draft is a placeholder and must be confirmed before release.",
            meta={"icon": "💡", "color": "blue_background"},
        )
        table_id = client.add(page_id, "table", meta={"table_width": 2, "has_column_header": True})
        client.add(table_id, "table_row", meta={"cells": [["Plan"], ["Price"]]})
        client.add(table_id, "table_row", meta={"cells": [["Pro"], ["$99/mo"]]})
        return client, page_id
