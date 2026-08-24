"""Panel-facing REST surface for Milestone 6: the explicit Start/Stop
listening lifecycle. Vexa listening is a user-initiated action — opening
the panel must NOT spawn a bot — so these routes are the only way a Vexa
session begins listening; the frontend sends the meeting number it already
holds from Zoom's SDK context (never a typed/pasted URL), and everything
else stays server-side.

Both routes follow the same idempotent get_or_create_session pattern as
routes_session.py, and return the provider's resulting status so the panel
doesn't have to wait for the next /state poll.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.encoding import decode_meeting_uuid
from app.drafting.session import get_or_create_session

router = APIRouter()


class StartListeningRequest(BaseModel):
    # Zoom's getMeetingContext().meetingNumber — the numeric meeting ID the
    # panel already has. meeting_url is an escape hatch for a real invite
    # link when one is available (e.g. a future host-side setup); the
    # backend constructs the canonical zoom.us/j/<id> join URL when only
    # the number is given. passcode is EPHEMERAL and attempt-scoped: sent
    # to Vexa's native passcode field for a passcode-protected meeting,
    # never persisted, never logged (the provider clears it the moment the
    # bot request settles). Optional — the default flow starts with no
    # passcode and only asks for one when Vexa reports passcode_required.
    meeting_number: str | None = None
    meeting_url: str | None = None
    passcode: str | None = None


@router.post("/api/meetings/{meeting_uuid}/listen")
async def start_listening(meeting_uuid: str, body: StartListeningRequest, request: Request):
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    try:
        status = await session.start_listening(
            meeting_number=body.meeting_number,
            meeting_url=body.meeting_url,
            passcode=body.passcode,
        )
    except ValueError as exc:
        # e.g. the active provider is Manual (nothing to connect) — 409,
        # the same convention the other session-state conflicts use.
        raise HTTPException(409, str(exc)) from exc
    return {"status": status}


@router.post("/api/meetings/{meeting_uuid}/listen/stop")
async def stop_listening(meeting_uuid: str, request: Request):
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    status = await session.stop_listening()
    return {"status": status}
