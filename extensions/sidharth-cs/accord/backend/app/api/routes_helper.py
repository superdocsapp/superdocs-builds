"""Control channel for the Mac capture-helper (Architecture B, spike).

The Zoom panel calls the HTTPS start/stop routes; the backend broadcasts
the command to every connected helper over its OUTBOUND WSS; the helper
ACKs; the ACK is matched back to the meeting session by meeting_uuid.

No audio is captured here — the helper only carries START/STOP/PING and
ACKs. No localhost in this path; the helper always connects outbound.
"""

from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.api.encoding import decode_meeting_uuid
from app.core.config import get_settings
from app.drafting.session import get_or_create_session
from app.helper.registry import helper_registry

logger = logging.getLogger("routes.helper")
router = APIRouter()


@router.websocket("/api/ws/helper")
async def helper_ws(websocket: WebSocket):
    """The Mac helper's outbound WSS home. Authenticated by ?token= so the
    socket is not a public command channel. Reads ACKs and updates the
    matching meeting session's helper_status."""
    settings = get_settings()
    token = websocket.query_params.get("token", "")
    # compare_digest, not ==: a plain string comparison returns as soon as it
    # finds a differing byte, which leaks the length of the matching prefix
    # to anyone who can time the handshake. Same auth decision, no timing
    # side channel.
    if not settings.helper_auth_token or not hmac.compare_digest(
        token, settings.helper_auth_token
    ):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    await helper_registry.register(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            cmd = msg.get("cmd")
            uuid = msg.get("meeting_uuid")
            if cmd == "started" and uuid:
                # The helper got START and is (conceptually) capturing.
                session = await get_or_create_session(
                    uuid, websocket.app.state.superdocs_client
                )
                await session.set_helper_status("listening")
            elif cmd == "stopped" and uuid:
                session = await get_or_create_session(
                    uuid, websocket.app.state.superdocs_client
                )
                await session.set_helper_status("ready")
    except WebSocketDisconnect:
        pass
    finally:
        await helper_registry.unregister(websocket)


@router.post("/api/meetings/{meeting_uuid}/helper/start")
async def helper_start(meeting_uuid: str, request: Request):
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    if not helper_registry.connected:
        await session.set_helper_status("disconnected")
        raise HTTPException(503, "Audio helper is not running on this device")
    await helper_registry.broadcast({"cmd": "start", "meeting_uuid": meeting_uuid})
    await session.set_helper_status("connecting")
    return {"status": "connecting"}


@router.post("/api/meetings/{meeting_uuid}/helper/stop")
async def helper_stop(meeting_uuid: str, request: Request):
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    # Carry the meeting_uuid so the helper can echo it in its "stopped" ACK,
    # which is how the backend matches the ACK back to this session.
    await helper_registry.broadcast({"cmd": "stop", "meeting_uuid": meeting_uuid})
    await session.set_helper_status("stopping")
    return {"status": "stopping"}
