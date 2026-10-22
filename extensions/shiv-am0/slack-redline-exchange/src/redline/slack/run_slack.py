from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from ..config import Settings, load_settings
from ..core.negotiation import NegotiationService
from ..core.store import Store
from ..superdocs.client import SuperDocsClient
from ..superdocs.fake import FakeSuperDocs
from ..superdocs.transport import HTTPTransport, Transport
from .bolt_app import RoutingMessenger, SlackMessenger, create_app, register_handlers

logger = logging.getLogger("redline")

REQUIRED_FOR_SLACK = (
    ("slack_bot_token", "xoxb-...", "OAuth & Permissions → Bot User OAuth Token"),
    ("slack_app_token", "xapp-...", "Basic Information → App-Level Tokens (connections:write)"),
)


PARTIAL_TWO_WORKSPACE = (
    "vendor_bot_token",
    "vendor_app_token",
    "customer_bot_token",
    "customer_app_token",
)


def _validate(settings: Settings) -> list[str]:
    """Fail fast with the exact fix, rather than a confusing Slack handshake error."""
    problems: list[str] = []
    supplied = [f for f in PARTIAL_TWO_WORKSPACE if getattr(settings, f)]
    if supplied and not settings.two_workspace_mode:
        missing = [f.upper() for f in PARTIAL_TWO_WORKSPACE if not getattr(settings, f)]
        problems.append(
            "two-workspace mode is half configured: "
            f"{', '.join(missing)} still empty. Set all four, or clear the ones you set "
            "to fall back to single-workspace mode."
        )
    if settings.two_workspace_mode:
        if settings.vendor_team_id == settings.customer_team_id:
            problems.append(
                "VENDOR_TEAM_ID and CUSTOMER_TEAM_ID are identical, but two-workspace "
                "mode expects a different Slack workspace per company"
            )
        return problems

    for field, shape, where in REQUIRED_FOR_SLACK:
        value = getattr(settings, field)
        if not value:
            problems.append(
                f"{field.upper()} is not set (expected {shape}); find it in your Slack "
                f"app config under: {where}"
            )
    if not settings.fake_mode and not settings.superdocs_api_key:
        problems.append(
            "FAKE_MODE=false but SUPERDOCS_API_KEY is empty; either set the key or "
            "set FAKE_MODE=true to run against the built-in fake"
        )
    if settings.shared_channel.startswith("C_") and len(settings.shared_channel) < 9:
        problems.append(
            f"SHARED_CHANNEL={settings.shared_channel!r} still looks like the placeholder "
            "from .env.example; set it to the real Slack channel ID (starts with C, "
            "copied from the channel's About tab)"
        )
    return problems


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    settings = load_settings()

    problems = _validate(settings)
    if problems:
        print("Cannot start the Slack app:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nCopy .env.example to .env and fill it in, then re-run:"
            "\n  uv run python -m redline.slack.run_slack\n",
            file=sys.stderr,
        )
        raise SystemExit(1)

    store = Store(settings.database_path)
    transport: Transport
    if settings.fake_mode:
        transport = FakeSuperDocs()
        logger.warning(
            "FAKE_MODE=true — running against the in-process SuperDocs fake, so nothing "
            "will appear in the SuperDocs UI. Set FAKE_MODE=false in .env to go live."
        )
    else:
        transport = HTTPTransport(settings.superdocs_base_url, settings.superdocs_api_key)
        logger.info("using the live SuperDocs API at %s", settings.superdocs_base_url)

    client = SuperDocsClient(transport)

    # Build in dependency order: app(s) -> messenger (needs their web clients) ->
    # service (needs the messenger) -> handlers (need the service).
    apps: dict[str, Any] = {}
    if settings.two_workspace_mode:
        for side in ("vendor", "customer"):
            apps[side] = create_app(settings, side)
        messenger = RoutingMessenger(
            settings, {side: app.client for side, app in apps.items()}
        )
        logger.info("two-workspace mode: one Slack app per company (real Slack Connect)")
    else:
        apps["vendor"] = create_app(settings)
        messenger = SlackMessenger(apps["vendor"])
        logger.info("single-workspace mode: one Slack app, sides resolved per user")

    service = NegotiationService(settings, store, client, messenger)
    for side, app in apps.items():
        register_handlers(
            app, service, settings, owning_side=side if settings.two_workspace_mode else None
        )

    logger.info("shared channel:   %s", settings.shared_channel)
    logger.info("vendor internal:  %s", settings.vendor_internal_channel)
    logger.info("customer internal:%s", settings.customer_internal_channel)
    logger.info("approval policy:  %s", settings.approval_policy)
    logger.info("database:         %s", settings.database_path)

    recovered = store.jobs_in_states("running", "awaiting_review")
    if recovered:
        logger.info("resuming %d in-flight job(s) from the last run", len(recovered))
        await service.recover_pending()

    # One Socket Mode connection per installed app. They share this process, this
    # service and this database, so a decision arriving over either connection sees the
    # same state; gather keeps both alive for the life of the process.
    connections = [
        AsyncSocketModeHandler(app, settings.app_token_for_side(side)).start_async()
        for side, app in apps.items()
    ]
    logger.info(
        "connecting to Slack over Socket Mode (%d connection(s))… (ctrl-c to stop)",
        len(connections),
    )
    await asyncio.gather(*connections)


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    run()
