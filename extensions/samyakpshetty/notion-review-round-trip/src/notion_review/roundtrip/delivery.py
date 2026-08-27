"""How the review document reaches the reviewers.

The round-trip is only as usable as its first step: a document that never leaves the machine is
not out for review. This is the seam that hands it over, and it has two implementations.

The default attaches the document to the **Notion row** that asked for the review, so asking and
receiving happen in the same place and nobody leaves the application they work in. A **folder** is
the other — a real channel, not a placeholder, when it is a shared Drive, Dropbox or SharePoint
folder the reviewers already have.

Delivery is a seam rather than a hard-coded transport because the round-trip does not care how the
document travelled: it carries its own review-round id and is matched however it comes back. An
email adapter belongs here too — but only alongside an email *intake*, since a reviewer who is
emailed a document will reply to it, and a channel that sends without receiving is a promise the
system cannot keep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from notion_review.logging import get_logger
from notion_review.notion.base import NotionClient
from notion_review.roundtrip.requests import DOCUMENT_PROP, attachment_properties

_log = get_logger("notion_review.delivery")


@dataclass
class Deliverable:
    """A review document on its way to the people who will mark it up."""

    filename: str
    content: bytes
    recipients: list[str] = field(default_factory=list)
    subject: str = "Document for review"
    body: str = ""
    reference: str = ""  # the Notion request row this came from, for channels that write back


@runtime_checkable
class Delivery(Protocol):
    """Somewhere a review document can be handed to its reviewers."""

    def deliver(self, item: Deliverable) -> str:
        """Send it; returns a short receipt describing where it went, for the audit trail."""
        ...


class FolderDelivery:
    """Write the document to a folder the reviewers can reach.

    Synced to a shared drive, this is how a team already passes files around: the document appears
    where the reviewers look, and the marked-up copy goes back into the intake folder.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def deliver(self, item: Deliverable) -> str:
        destination = self.directory / item.filename
        destination.write_bytes(item.content)
        _log.info(
            "delivered_to_folder",
            extra={"path": str(destination), "recipients": len(item.recipients)},
        )
        return f"written to {destination}"


class NotionRowDelivery:
    """Attach the review document to the Notion row that asked for it.

    This is the shortest possible distance between asking for a review and having the document:
    the person clicks the button on their page, and moments later the styled Word file is sitting
    on that row, in Notion, where they already are. No folder on a server, no sync client, and no
    terminal anywhere in the loop — and because the round id is stamped inside the file, the copy
    that comes back is matched however it travels.

    A reviewer inside the workspace collects it from the row and drops their marked-up copy back
    onto the same row. A reviewer outside it is sent the file by the owner, from Notion, and the
    reply goes back on the row the same way.
    """

    DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def __init__(self, notion: NotionClient, *, property_name: str = DOCUMENT_PROP) -> None:
        self._notion = notion
        self._property = property_name

    def deliver(self, item: Deliverable) -> str:
        if not item.reference:
            raise ValueError("a Notion-row delivery needs the request row it belongs to")
        upload_id = self._notion.upload_file(
            content=item.content, filename=item.filename, content_type=self.DOCX_MIME
        )
        self._notion.update_row(
            page_id=item.reference,
            properties=attachment_properties(
                upload_id=upload_id, filename=item.filename, name=self._property
            ),
        )
        _log.info(
            "delivered_to_notion_row",
            extra={"row": item.reference, "document": item.filename, "bytes": len(item.content)},
        )
        return f"attached to this row as {item.filename}"
