"""Build the Notion and SuperDocs clients for the configured provider.

``fake`` returns the deterministic in-memory clients (keyless tests, demo); ``live`` returns the
HTTP clients after validating that credentials are present. Everything downstream depends only on
the typed protocols, so the choice is invisible past this seam.
"""

from __future__ import annotations

from notion_review.config import Config
from notion_review.notion.base import NotionClient
from notion_review.notion.fake import FakeNotionClient
from notion_review.roundtrip.delivery import Delivery, FolderDelivery, NotionRowDelivery
from notion_review.roundtrip.intake import FolderIntake, Intake, NotionRowIntake
from notion_review.roundtrip.requests import RequestBoards
from notion_review.superdocs.base import SuperDocsClient
from notion_review.superdocs.fake import FakeSuperDocsClient


def build_clients(config: Config) -> tuple[NotionClient, SuperDocsClient]:
    """Return (notion, superdocs) clients for ``config.provider``."""
    if config.provider == "live":
        config.require_live()
        from notion_review.notion.live import LiveNotionClient
        from notion_review.superdocs.live import LiveSuperDocsClient

        assert config.notion_token is not None  # guaranteed by require_live
        assert config.superdocs_api_key is not None
        notion: NotionClient = LiveNotionClient(
            token=config.notion_token, version=config.notion_version, config=config
        )
        superdocs: SuperDocsClient = LiveSuperDocsClient(
            api_key=config.superdocs_api_key, base_url=config.superdocs_base_url, config=config
        )
        return notion, superdocs
    return FakeNotionClient(), FakeSuperDocsClient()


def build_boards(config: Config, notion: NotionClient) -> RequestBoards:
    """The *Review requests* boards this deployment serves.

    Found, not configured: a board is served because someone shared it with the integration in
    Notion, which is the same gesture that grants access to it. Adding a team is adding a board;
    nothing is redeployed and no id is copied anywhere. ``NOTION_REQUESTS_DB`` remains as a pin
    for a deployment that should serve exactly one board in a workspace holding several.
    """
    pinned = [config.notion_requests_database_id] if config.notion_requests_database_id else []
    return RequestBoards(notion, pinned=pinned)


def build_channel(
    config: Config, notion: NotionClient, *, inbox: str, outbox: str, boards: RequestBoards
) -> tuple[Intake, Delivery]:
    """How the document reaches reviewers and comes back — both halves, chosen together.

    They are returned as a pair on purpose: a channel that can send but not receive is a promise
    the round-trip cannot keep, so the two are never configured apart.

    With at least one requests board in reach, the default keeps the whole handoff **inside
    Notion** — the document is attached to the row that asked for it, and reviewers drop their
    marked-up copies back onto the same row, so nobody touches a folder or a terminal.
    ``HANDOFF=folder`` uses a watched directory instead, which is a real channel when it is a
    synced shared drive and is also what a deployment with no board in reach falls back to.

    Either way the round-trip is unchanged: the document carries its own review-round id and is
    matched however it comes home.
    """
    if config.handoff == "notion" and boards.ids():
        return NotionRowIntake(notion, boards=boards), NotionRowDelivery(notion)
    return FolderIntake(inbox), FolderDelivery(outbox)
