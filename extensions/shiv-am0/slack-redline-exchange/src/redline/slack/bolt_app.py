from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from slack_bolt.async_app import AsyncApp

from ..config import Settings
from ..core import boundary
from ..core.negotiation import MessengerPort, NegotiationService
from . import handlers

logger = logging.getLogger("redline.slack")

DECISION_ACTION_PATTERN = re.compile(r"^redline:decide:")


class SlackMessenger(MessengerPort):
    """Thin MessengerPort adapter over a real Bolt AsyncApp client."""

    def __init__(self, app: AsyncApp):
        self._client = app.client

    async def post_message(
        self,
        channel: str,
        blocks: list[dict[str, Any]],
        text: str,
        thread_ts: str | None = None,
    ) -> str:
        response = await self._client.chat_postMessage(
            channel=channel, blocks=blocks, text=text, thread_ts=thread_ts
        )
        return str(response["ts"])

    async def update_message(
        self, channel: str, ts: str, blocks: list[dict[str, Any]], text: str
    ) -> None:
        await self._client.chat_update(channel=channel, ts=ts, blocks=blocks, text=text)

    async def upload_file(
        self, channel: str, filename: str, content: bytes, initial_comment: str = ""
    ) -> None:
        await self._client.files_upload_v2(
            channel=channel,
            filename=filename,
            content=content,
            initial_comment=initial_comment,
        )


class RoutingMessenger(MessengerPort):
    """Posts each channel's traffic through the workspace that owns that channel.

    In real Slack Connect the two companies run separate apps in separate workspaces,
    so there is no single client that can reach every channel: only the customer's bot
    can post into the customer's internal channel, and vice versa. This routes by
    channel and keeps the shared channel pinned to one owning bot, because Slack lets an
    app edit only its own messages and proposal cards are edited in place.
    """

    def __init__(self, settings: Settings, clients: dict[str, Any]):
        self._settings = settings
        self._clients = clients

    def _client_for(self, channel: str):
        side = self._settings.side_owning_channel(channel)
        try:
            return self._clients[side]
        except KeyError as exc:  # pragma: no cover - guarded at startup
            raise RuntimeError(
                f"no Slack client configured for the {side} workspace, needed to reach "
                f"channel {channel}"
            ) from exc

    async def post_message(
        self,
        channel: str,
        blocks: list[dict[str, Any]],
        text: str,
        thread_ts: str | None = None,
    ) -> str:
        response = await self._client_for(channel).chat_postMessage(
            channel=channel, blocks=blocks, text=text, thread_ts=thread_ts
        )
        return str(response["ts"])

    async def update_message(
        self, channel: str, ts: str, blocks: list[dict[str, Any]], text: str
    ) -> None:
        await self._client_for(channel).chat_update(
            channel=channel, ts=ts, blocks=blocks, text=text
        )

    async def upload_file(
        self, channel: str, filename: str, content: bytes, initial_comment: str = ""
    ) -> None:
        await self._client_for(channel).files_upload_v2(
            channel=channel,
            filename=filename,
            content=content,
            initial_comment=initial_comment,
        )


async def _download_slack_file(url: str, bot_token: str) -> bytes:
    """Slack file URLs are private; they need the bot token as a bearer header."""
    async with httpx.AsyncClient(timeout=60.0) as http_client:
        response = await http_client.get(
            url, headers={"Authorization": f"Bearer {bot_token}"}
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"could not download the shared file (HTTP {response.status_code}); "
                "check the bot has files:read and is a member of the channel"
            )
        return response.content


def _should_ignore_duplicate(
    settings: Settings, owning_side: str | None, uploader_team: str
) -> bool:
    """In two-workspace mode, only the uploader's own workspace ingests their file.

    Single-workspace mode has exactly one listener, so nothing is ever ignored -- and a
    file whose team we cannot determine is always handled rather than dropped, since
    losing a document is worse than briefly risking a duplicate.
    """
    if owning_side is None or not settings.two_workspace_mode or not uploader_team:
        return False
    return uploader_team != settings.team_id_for_side(owning_side)


def create_app(settings: Settings, side: str | None = None) -> AsyncApp:
    """Build the Bolt app on its own, before the service exists.

    The service needs a messenger, and the messenger needs this app's web client, so the
    app has to be created first; handlers are registered afterwards via
    `register_handlers` once the service is ready.
    """
    return AsyncApp(
        token=settings.bot_token_for_side(side) if side else settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )


def register_handlers(
    app: AsyncApp,
    service: NegotiationService,
    settings: Settings,
    owning_side: str | None = None,
) -> AsyncApp:
    """Wire the Slack listeners onto an app.

    `owning_side` names the workspace this app is installed in, and is only meaningful
    in two-workspace mode: both companies' bots sit in the shared Connect channel, so
    both receive the same `file_shared` event. Without a rule for which one acts, one
    dropped document would open two deals. The rule is that the uploader's own
    workspace handles it.
    """
    async def _report(respond: Any, message: str) -> None:
        """Reply privately to the person who acted, never into the shared channel.

        Errors are operational noise for the acting user; broadcasting them to the
        counterparty would leak how one side is driving the negotiation.

        `replace_original=False` is load-bearing, not decoration. Slack's default for a
        response_url reply to a button click is to REPLACE the message that carried the
        button -- so reporting an error would overwrite the proposal card itself, in
        channel, for everyone, destroying the buttons the user still needs. An error
        report must never be able to damage the thing it is reporting on.
        """
        try:
            await respond(
                text=message, response_type="ephemeral", replace_original=False
            )
        except Exception:  # noqa: BLE001 - reporting must never mask the original error
            logger.exception("failed to report an error back to Slack")

    @app.command("/redline")
    async def on_command(ack, command, respond):  # noqa: ANN001
        # Slack requires an ack within 3 seconds. Everything slow happens after it.
        await ack()
        try:
            result = await handlers.handle_slash_command(
                service,
                settings,
                channel_id=command["channel_id"],
                user_id=command["user_id"],
                team_id=command["team_id"],
                text=command.get("text", ""),
            )
            logger.info("slash command handled: %s", result)
        except boundary.BoundaryViolation as exc:
            await _report(respond, f":no_entry: {exc.reason}")
        except (ValueError, KeyError) as exc:
            await _report(respond, f":warning: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("unexpected error handling /redline")
            await _report(respond, f":rotating_light: unexpected error: {exc}")

    # Bolt's action matcher accepts a literal str or a compiled re.Pattern -- nothing
    # else. Every decision button's action_id is "redline:decide:<proposal>:<side>:<yes>",
    # so one prefix pattern catches them all.
    @app.action(DECISION_ACTION_PATTERN)
    async def on_decide(ack, action, body, respond):  # noqa: ANN001
        await ack()
        team_id = body.get("team", {}).get("id") or body.get("user", {}).get("team_id", "")
        try:
            result = await handlers.handle_block_action(
                service,
                settings,
                action_id=action["action_id"],
                user_id=body["user"]["id"],
                team_id=team_id,
            )
            logger.info("decision recorded: %s", result)
        except ValueError as exc:
            await _report(respond, f":warning: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("unexpected error handling a decision")
            await _report(respond, f":rotating_light: unexpected error: {exc}")

    @app.event("file_shared")
    async def on_file_shared(event, client):  # noqa: ANN001
        """A file dropped in the shared channel starts a deal, or joins the open one.

        Assumption, documented in the README: the first file shared in the channel opens
        a new deal; any later file joins that deal as a supporting document rather than
        silently replacing the contract under negotiation.
        """
        channel_id = event.get("channel_id") or event.get("channel", "")
        try:
            info = await client.files_info(file=event["file_id"])
            file_meta = info["file"]
            uploader_team = file_meta.get("user_team") or file_meta.get("source_team", "")
            if _should_ignore_duplicate(settings, owning_side, uploader_team):
                logger.debug(
                    "ignoring file_shared from team %s; the other workspace owns it",
                    uploader_team,
                )
                return
            content = await _download_slack_file(
                file_meta["url_private_download"],
                settings.bot_token_for_side(owning_side or "vendor"),
            )
            open_deal = service.latest_open_deal(channel_id)
            await handlers.handle_file_share(
                service,
                settings,
                channel_id=channel_id,
                user_id=file_meta.get("user", ""),
                team_id=file_meta.get("user_team") or file_meta.get("source_team", ""),
                filename=file_meta.get("name", "document"),
                file_bytes=content,
                attach_to_deal_id=open_deal.id if open_deal else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("could not ingest a shared file")
            await client.chat_postMessage(
                channel=channel_id,
                text=f":warning: could not ingest that file: {exc}",
            )

    @app.event("message")
    async def ignore_messages(**_: Any) -> None:
        """Bolt warns loudly about unhandled message events; we intentionally ignore them.

        This app is driven by slash commands and buttons, not by free-text chat, so
        ordinary channel conversation is none of its business.
        """

    return app


def create_bolt_app(service: NegotiationService, settings: Settings) -> AsyncApp:
    """Convenience wrapper: build the app and register handlers in one call."""
    return register_handlers(create_app(settings), service, settings)
