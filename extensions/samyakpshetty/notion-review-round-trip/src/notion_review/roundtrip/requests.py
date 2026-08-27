"""Starting a review from inside Notion, without a terminal.

Sending a page for review was a developer command, which is not a workflow anyone would use. This
makes it a Notion action instead: a **Review requests** database the team keeps in their workspace.
To send a page out, someone adds a row — the page to review, who should review it — and sets
Status to *Requested*. The service picks it up, runs the round-trip, delivers the document, and
writes back the round it created.

It is deliberately the same mechanism as the approval queue: the service already polls Notion for
the owner's decisions, so it polls for their requests too. One pattern, both directions, and the
owner never leaves Notion.

A row is also what makes the whole thing a single button. Notion's button blocks cannot be created
through the public API — they read back as ``"unsupported"`` — but a person can add one to their
page in Notion itself, with the *Add page to* action pointed at this database and the page filled
in. Clicking it writes the row, and everything below follows: the document goes out on that row,
the marked-up copies come back onto it, and the changes appear on the page for approval.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from notion_review.logging import get_logger
from notion_review.notion.base import NotionClient, NotionError
from notion_review.notion.models import FileRef, QueueRow

_log = get_logger("notion_review.requests")

STATUS_REQUESTED = "Requested"
STATUS_SENT = "Sent"
STATUS_FAILED = "Failed"

REQUESTS_DB_TITLE = "Review requests"  # the exact title that marks a board as ours
DOCUMENT_PROP = "Document"  # the styled .docx we send out, attached to the row
RETURNED_PROP = "Returned"  # where reviewers put their marked-up copies back
TAKEN_IN_PROP = "Taken in"  # returned files already handed to the round-trip

_PROP_LIMIT = 1900
# A Notion page id is 32 hex characters, with or without dashes — pull it out of a pasted URL.
_PAGE_ID = re.compile(r"([0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12})", re.I)
_EMAIL = re.compile(r"[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+")


@dataclass
class ReviewRequest:
    """One row of the requests database: a page someone wants sent out for review."""

    row_id: str
    page_id: str
    reviewers: list[str]
    note: str = ""


def request_properties() -> dict[str, Any]:
    """The schema of the requests database — what a person fills in to start a review."""
    return {
        "Page": {"title": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": STATUS_REQUESTED, "color": "yellow"},
                    {"name": STATUS_SENT, "color": "green"},
                    {"name": STATUS_FAILED, "color": "red"},
                ]
            }
        },
        "Page URL": {"url": {}},
        "Reviewers": {"rich_text": {}},
        "Round": {"rich_text": {}},
        "Result": {"rich_text": {}},
        # The document goes out on the row and comes back on the row, so the whole handoff is
        # visible in Notion and the owner never goes looking in a folder on a server.
        DOCUMENT_PROP: {"files": {}},
        RETURNED_PROP: {"files": {}},
        TAKEN_IN_PROP: {"rich_text": {}},
    }


def files_in(properties: dict[str, Any], name: str) -> list[FileRef]:
    """The files attached to one property, as name and (signed, expiring) URL."""
    prop = properties.get(name) or {}
    entries = prop.get("files")
    if not isinstance(entries, list):
        return []
    files: list[FileRef] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Notion hosts it (``file``) or it was linked from elsewhere (``external``); both read
        # the same way here, and either is a document a reviewer can have put there.
        holder = entry.get("file") or entry.get("external") or {}
        url = holder.get("url", "") if isinstance(holder, dict) else ""
        if url:
            files.append(FileRef(name=str(entry.get("name") or ""), url=str(url)))
    return files


def attachment_properties(*, upload_id: str, filename: str, name: str = DOCUMENT_PROP) -> Any:
    """The payload that attaches an uploaded file to a row's ``files`` property."""
    return {
        name: {
            "type": "files",
            "files": [{"type": "file_upload", "file_upload": {"id": upload_id}, "name": filename}],
        }
    }


def taken_in(properties: dict[str, Any]) -> set[str]:
    """Which returned files this row has already handed over, by name."""
    return {name for name in _text_of(properties, TAKEN_IN_PROP).split("\n") if name}


def taken_in_properties(names: set[str]) -> dict[str, Any]:
    """Record which returned files have been handed over, so a poll does not re-fetch them.

    Kept on the row rather than in memory so a restart does not download every attachment again.
    It is an optimisation, not the correctness boundary: a file that slips through is recognised
    by its content hash further in and costs nothing.
    """
    listed = "\n".join(sorted(names))[:_PROP_LIMIT]
    return {TAKEN_IN_PROP: {"rich_text": [{"type": "text", "text": {"content": listed}}]}}


def create_request_database(notion: NotionClient, *, parent_page_id: str) -> str:
    """Create a requests database in the workspace; returns its id.

    Nothing needs to be told about it afterwards — :class:`RequestBoards` finds it because it is
    shared with the integration.
    """
    database = notion.create_database(
        parent_page_id=parent_page_id,
        title=REQUESTS_DB_TITLE,
        properties=request_properties(),
    )
    _log.info("requests_database_created", extra={"database_id": database.id})
    return database.id


class RequestBoards:
    """Every *Review requests* database this integration can see.

    Which boards exist is a fact about the workspace, not about the deployment, so it is
    discovered rather than configured. Notion's search returns only what someone has explicitly
    shared with the connection, so a team starts using this by sharing their board in Notion —
    the same gesture that grants access — and stops by unsharing it. Nothing is redeployed, no
    id is copied into an environment file, and a workspace with five teams and five boards needs
    no more setup than a workspace with one.

    The result is cached briefly, because this is polled on a loop and the answer changes about
    as often as somebody creates a database. A board shared while the service is running is
    picked up within one refresh.
    """

    def __init__(
        self,
        notion: NotionClient,
        *,
        pinned: Sequence[str] = (),
        ttl_s: float = 60.0,
        gone_cooldown_s: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._notion = notion
        # An explicit id pins the service to one board and skips discovery — for a workspace
        # holding several boards where a deployment should serve exactly one.
        self._pinned = [board for board in pinned if board]
        self._ttl_s = ttl_s
        self._gone_cooldown_s = gone_cooldown_s
        self._clock = clock
        self._cached: list[str] = []
        self._read_at: float | None = None
        self._gone: dict[str, float] = {}

    def forget(self, board_id: str) -> None:
        """Stop serving a board that has vanished underneath us — for a while, not forever.

        Archiving, unsharing or deleting a board makes it unreadable at once, but Notion's search
        keeps listing it until the index catches up, and it is listed as perfectly healthy while
        it does. Without this, every pass would rediscover a board it cannot read and warn about
        it again, forever.

        A cooldown rather than a tombstone, because the two things that look identical here are
        not: a board whose index entry is merely stale, and a board somebody archived by mistake
        and restored a minute later. Suppressing it permanently would serve the first case and
        silently abandon the second, so it is retried once the cooldown passes — and if it really
        is gone, it costs one failed read every cooldown instead of one every pass.
        """
        self._gone[board_id] = self._clock()
        self._cached = [board for board in self._cached if board != board_id]
        _log.info("board_forgotten", extra={"board": board_id})

    def ids(self) -> list[str]:
        if self._pinned:
            return list(self._pinned)
        now = self._clock()
        if self._read_at is not None and now - self._read_at < self._ttl_s:
            return list(self._cached)
        try:
            found = self._notion.search_databases(REQUESTS_DB_TITLE)
        except NotionError as exc:
            # Keep serving the boards we already know: a search that fails is no reason to stop
            # taking in reviews that are already under way.
            _log.warning("board_discovery_failed", extra={"error": str(exc)})
            return list(self._cached)
        # Notion's search matches loosely, so it also returns our own per-round review queues.
        # Only an exact title is a request board — and only one that still exists: the search
        # index lags behind an archive, so a board that has just gone can still be listed.
        discovered = [
            db.id for db in found if db.title.strip() == REQUESTS_DB_TITLE and not db.archived
        ]
        self._gone = {
            board: at for board, at in self._gone.items() if now - at < self._gone_cooldown_s
        }
        discovered = [board for board in discovered if board not in self._gone]
        if discovered != self._cached:
            _log.info(
                "request_boards_discovered",
                extra={"boards": len(discovered), "was": len(self._cached)},
            )
        self._cached = discovered
        self._read_at = now
        return list(discovered)


def _text_of(row: dict[str, Any], name: str) -> str:
    prop = row.get(name) or {}
    runs = prop.get("rich_text") or prop.get("title") or []
    if isinstance(runs, list):
        return "".join(r.get("plain_text", "") for r in runs)
    return ""


def parse_request(row: QueueRow, properties: dict[str, Any]) -> ReviewRequest | None:
    """Read one row into a request, or ``None`` if it does not name a page we can act on."""
    url_prop = properties.get("Page URL") or {}
    haystack = " ".join(
        [
            str(url_prop.get("url") or ""),
            _text_of(properties, "Page"),
            _text_of(properties, "Round"),
        ]
    )
    match = _PAGE_ID.search(haystack)
    if not match:
        return None
    return ReviewRequest(
        row_id=row.page_id,
        page_id=match.group(1),
        reviewers=_EMAIL.findall(_text_of(properties, "Reviewers")),
        note=_text_of(properties, "Result"),
    )


def mark_request(
    notion: NotionClient, *, row_id: str, status: str, round_id: str = "", result: str = ""
) -> None:
    """Write back what happened to a request, so the row tells its own story."""
    properties: dict[str, Any] = {"Status": {"select": {"name": status}}}
    if round_id:
        properties["Round"] = {
            "rich_text": [{"type": "text", "text": {"content": round_id[:_PROP_LIMIT]}}]
        }
    if result:
        properties["Result"] = {
            "rich_text": [{"type": "text", "text": {"content": result[:_PROP_LIMIT]}}]
        }
    notion.update_row(page_id=row_id, properties=properties)
