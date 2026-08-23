"""Panel-facing SSE stream (design doc §21, §26) — the backend as SSE
*server* to the browser, distinct from the SuperDocs job-status SSE the
backend would consume as a *client* (not used in M3; job status is polled,
see session.py `_poll_job`).

Relies on Starlette's standard disconnect handling: when the browser drops
the connection, the ASGI server cancels this request's task, which raises
into whichever `await` the generator is suspended on (including a blocked
`queue.get()`) and runs the `finally` — no manual `is_disconnected()` poll
needed.

Two additions beyond the bare stream, both standard practice for SSE
through any CDN/proxy (this app's traffic runs through Cloudflare's
tunnel), neither optional in practice:
  - Explicit no-buffering/no-cache response headers. Without them, an
    intermediary is free to buffer or cache what looks like an ordinary
    HTTP response instead of forwarding bytes as they're written, which
    can prevent the browser's EventSource from ever seeing the stream
    open at all.
  - A periodic heartbeat comment (a bare `:` line — valid SSE, ignored by
    EventSource, never reaches `onmessage`) so the connection keeps
    producing bytes even during a long silent gap (SuperDocs edits can
    take minutes) — otherwise an idle-timeout anywhere in the path can
    kill the connection with nothing left to signal it stayed alive.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.encoding import decode_meeting_uuid
from app.drafting.session import get_or_create_session

router = APIRouter()

_HEARTBEAT_SECONDS = 15.0


@router.get("/api/meetings/{meeting_uuid}/events")
async def meeting_events(meeting_uuid: str, request: Request) -> StreamingResponse:
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    queue = session.subscribe()

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            session.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
