"""In-memory registry of connected Mac capture-helpers and their command
state. Control-channel spike only — the helper carries START/STOP/PING and
ACKs; it does not capture audio yet.

A helper connects OUTBOUND to the backend's /ws/helper WebSocket and stays
connected. When the panel starts/stops listening, the control routes
broadcast the command to every connected helper; the helper ACKs, and the
ACK is matched back to the meeting session by the meeting_uuid it echoes.

Single-helper demo model: broadcast to all authenticated helpers (in
practice one). Per-user helper routing is out of scope for this spike.
"""

from __future__ import annotations

import logging

from fastapi import WebSocket

logger = logging.getLogger("helper.registry")


class HelperRegistry:
    def __init__(self) -> None:
        # Connected helper sockets (a set; a helper stays connected for the
        # life of the process, so membership is a simple set).
        self._sockets: set[WebSocket] = set()

    @property
    def connected(self) -> bool:
        return bool(self._sockets)

    def __len__(self) -> int:
        return len(self._sockets)

    async def register(self, ws: WebSocket) -> None:
        self._sockets.add(ws)
        logger.info("helper connected (total=%d)", len(self._sockets))

    async def unregister(self, ws: WebSocket) -> None:
        self._sockets.discard(ws)
        logger.info("helper disconnected (total=%d)", len(self._sockets))

    async def broadcast(self, message: dict) -> int:
        """Send `message` to every connected helper. Drops and forgets a
        socket that fails to send (it is dead). Returns the number sent."""
        dead: list[WebSocket] = []
        for ws in list(self._sockets):
            try:
                import json

                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.unregister(ws)
        return len(self._sockets)


# Single-process module singleton — one registry for the whole app. The
# routes and the session's state_snapshot both read this, so the panel's
# /state can report whether a helper is connected without threading a
# request-scoped reference through the session object.
helper_registry = HelperRegistry()
