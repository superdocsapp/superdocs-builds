from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..core.negotiation import NegotiationService
from . import handlers


@dataclass
class CapturedMessage:
    channel: str
    ts: str
    blocks: list[dict[str, Any]]
    text: str
    thread_ts: str | None = None


@dataclass
class CapturedFile:
    channel: str
    filename: str
    content: bytes
    initial_comment: str = ""


class InMemoryMessenger:
    """A MessengerPort that records everything instead of calling the Slack API.

    Used by the simulator and directly by tests that want to inspect exactly what
    would have been posted to which channel.
    """

    def __init__(self) -> None:
        self.channels: dict[str, list[CapturedMessage]] = {}
        self.files: list[CapturedFile] = []
        self._ts_counter = itertools.count(1)

    def _next_ts(self) -> str:
        return f"{next(self._ts_counter):016d}.000000"

    async def post_message(
        self,
        channel: str,
        blocks: list[dict[str, Any]],
        text: str,
        thread_ts: str | None = None,
    ) -> str:
        ts = self._next_ts()
        self.channels.setdefault(channel, []).append(
            CapturedMessage(channel=channel, ts=ts, blocks=blocks, text=text, thread_ts=thread_ts)
        )
        return ts

    async def update_message(
        self, channel: str, ts: str, blocks: list[dict[str, Any]], text: str
    ) -> None:
        for message in self.channels.get(channel, []):
            if message.ts == ts:
                message.blocks = blocks
                message.text = text
                return
        raise KeyError(f"no message with ts {ts!r} in channel {channel!r}")

    async def upload_file(
        self, channel: str, filename: str, content: bytes, initial_comment: str = ""
    ) -> None:
        self.files.append(
            CapturedFile(
                channel=channel, filename=filename, content=content, initial_comment=initial_comment
            )
        )

    def all_messages(self) -> list[CapturedMessage]:
        return [m for messages in self.channels.values() for m in messages]


@dataclass
class WorkspaceUser:
    user_id: str
    team_id: str


@dataclass
class TwoWorkspaceSimulator:
    """Drives redline's plain-dict handlers through a fake two-workspace Slack Connect
    setup: vendor and customer each have their own team/internal channel, and both see
    the same shared channel. Business logic runs through the exact same handlers.py
    functions the real Bolt adapter uses — only the transport differs.
    """

    service: NegotiationService
    settings: Settings
    users: dict[str, WorkspaceUser] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.users.setdefault("vendor", WorkspaceUser("U_VENDOR", self.settings.vendor_team_id))
        self.users.setdefault(
            "customer", WorkspaceUser("U_CUSTOMER", self.settings.customer_team_id)
        )

    @property
    def messenger(self) -> InMemoryMessenger:
        assert isinstance(self.service.messenger, InMemoryMessenger)
        return self.service.messenger

    def _channel_for(self, side: str, shared: bool) -> str:
        return self.settings.shared_channel if shared else self.settings.internal_channel_for(side)

    async def send_file_share(
        self,
        side: str,
        filename: str,
        content: bytes,
        deal_name: str | None = None,
        attach_to_deal_id: str | None = None,
        role: str = "supporting",
        channel_id: str | None = None,
    ) -> dict[str, Any]:
        user = self.users[side]
        return await handlers.handle_file_share(
            self.service,
            self.settings,
            channel_id=channel_id or self.settings.shared_channel,
            user_id=user.user_id,
            team_id=user.team_id,
            filename=filename,
            file_bytes=content,
            deal_name=deal_name,
            attach_to_deal_id=attach_to_deal_id,
            role=role,
        )

    async def run_command(
        self, side: str, text: str, *, in_shared_channel: bool = True
    ) -> dict[str, Any]:
        user = self.users[side]
        channel_id = self._channel_for(side, shared=in_shared_channel)
        return await handlers.handle_slash_command(
            self.service,
            self.settings,
            channel_id=channel_id,
            user_id=user.user_id,
            team_id=user.team_id,
            text=text,
        )

    async def click(self, side: str, proposal_id: str, decision: str) -> dict[str, Any]:
        user = self.users[side]
        action_id = f"redline:decide:{proposal_id}:{side}:{decision}"
        return await handlers.handle_block_action(
            self.service,
            self.settings,
            action_id=action_id,
            user_id=user.user_id,
            team_id=user.team_id,
        )

    def shared_messages(self) -> list[CapturedMessage]:
        return self.messenger.channels.get(self.settings.shared_channel, [])

    def internal_messages(self, side: str) -> list[CapturedMessage]:
        return self.messenger.channels.get(self.settings.internal_channel_for(side), [])
