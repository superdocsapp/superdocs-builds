from __future__ import annotations

import pytest

from redline.slack.bolt_app import RoutingMessenger, _should_ignore_duplicate
from tests.conftest import make_settings

pytestmark = pytest.mark.anyio

TWO_WORKSPACE = {
    "vendor_bot_token": "xoxb-vendor",
    "vendor_app_token": "xapp-vendor",
    "customer_bot_token": "xoxb-customer",
    "customer_app_token": "xapp-customer",
}


class FakeClient:
    """Records what a single workspace's bot was asked to do."""

    def __init__(self, name: str):
        self.name = name
        self.posted: list[str] = []
        self.updated: list[str] = []

    async def chat_postMessage(self, channel, blocks, text, thread_ts=None):
        self.posted.append(channel)
        return {"ts": f"{self.name}.1"}

    async def chat_update(self, channel, ts, blocks, text):
        self.updated.append(channel)

    async def files_upload_v2(self, channel, filename, content, initial_comment=""):
        self.posted.append(channel)


def _routing(tmp_path):
    settings = make_settings(tmp_path, **TWO_WORKSPACE)
    clients = {"vendor": FakeClient("vendor"), "customer": FakeClient("customer")}
    return settings, clients, RoutingMessenger(settings, clients)


def test_two_workspace_mode_needs_all_four_tokens(tmp_path):
    """Half a configuration would post one company's messages with the other's bot."""
    assert make_settings(tmp_path).two_workspace_mode is False
    partial = make_settings(tmp_path, vendor_bot_token="x", vendor_app_token="y")
    assert partial.two_workspace_mode is False
    assert make_settings(tmp_path, **TWO_WORKSPACE).two_workspace_mode is True


async def test_each_internal_channel_is_reached_by_its_own_workspace(tmp_path):
    """Only the customer's bot can post into the customer's private channel."""
    settings, clients, messenger = _routing(tmp_path)

    await messenger.post_message(settings.vendor_internal_channel, [], "v")
    await messenger.post_message(settings.customer_internal_channel, [], "c")

    assert clients["vendor"].posted == [settings.vendor_internal_channel]
    assert clients["customer"].posted == [settings.customer_internal_channel]


async def test_the_shared_channel_is_always_served_by_one_bot(tmp_path):
    """Regression guard for a Slack rule: an app may only edit its own messages.

    Proposal cards are posted once and updated in place on every decision. If the two
    companies' bots took turns posting there, the first cross-company update would be
    rejected by Slack and the card would freeze.
    """
    settings, clients, messenger = _routing(tmp_path)

    await messenger.post_message(settings.shared_channel, [], "card")
    await messenger.update_message(settings.shared_channel, "1.0", [], "updated card")

    assert clients["vendor"].posted == [settings.shared_channel]
    assert clients["vendor"].updated == [settings.shared_channel]
    assert clients["customer"].posted == []
    assert clients["customer"].updated == [], (
        "the shared channel must have exactly one owning bot"
    )


def test_only_the_uploaders_workspace_ingests_a_shared_file(tmp_path):
    """Both bots see the same file in a Connect channel; only one may open a deal."""
    settings = make_settings(tmp_path, **TWO_WORKSPACE)

    assert not _should_ignore_duplicate(settings, "vendor", settings.vendor_team_id)
    assert _should_ignore_duplicate(settings, "customer", settings.vendor_team_id)

    assert not _should_ignore_duplicate(settings, "customer", settings.customer_team_id)
    assert _should_ignore_duplicate(settings, "vendor", settings.customer_team_id)


def test_single_workspace_never_ignores_a_file(tmp_path):
    """There is only one listener, so dropping anything would just lose the document."""
    settings = make_settings(tmp_path)
    assert not _should_ignore_duplicate(settings, None, settings.vendor_team_id)
    assert not _should_ignore_duplicate(settings, "vendor", settings.customer_team_id)


def test_a_file_with_no_team_is_handled_rather_than_dropped(tmp_path):
    """Losing a shared document is worse than briefly risking a duplicate."""
    settings = make_settings(tmp_path, **TWO_WORKSPACE)
    assert not _should_ignore_duplicate(settings, "vendor", "")


def test_tokens_resolve_per_side_and_fall_back_when_single(tmp_path):
    two = make_settings(tmp_path, **TWO_WORKSPACE)
    assert two.bot_token_for_side("vendor") == "xoxb-vendor"
    assert two.bot_token_for_side("customer") == "xoxb-customer"
    assert two.app_token_for_side("customer") == "xapp-customer"

    one = make_settings(tmp_path, slack_bot_token="xoxb-only")
    assert one.bot_token_for_side("vendor") == "xoxb-only"
    assert one.bot_token_for_side("customer") == "xoxb-only"
