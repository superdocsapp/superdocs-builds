"""The Zoom webhook receiver — Milestone 0 built the endpoint.url_validation
handshake and generic signature-verified logging; Milestone 4 adds the one
real branch, dispatching meeting.rtms_started/rtms_stopped to whichever
session's RTMSTranscriptProvider is waiting for it. Every other event still
just falls through to the generic log line at the bottom, unchanged.

Uses get_session, not get_or_create_session — a webhook for a meeting whose
panel never loaded has nowhere to deliver the info and should no-op, not
spin up a session with default provider selection.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request, Response

from app.core.config import get_settings
from app.core.security import build_url_validation_response, verify_signature
from app.drafting.session import get_session
from app.transcript.rtms_provider import RTMSTranscriptProvider

logger = logging.getLogger("zoom.webhooks")

router = APIRouter()

_RTMS_EVENTS = ("meeting.rtms_started", "meeting.rtms_stopped")


@router.post("/webhooks/zoom")
async def receive_zoom_webhook(request: Request) -> Response:
    raw_body = await request.body()
    settings = get_settings()

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("Zoom webhook: body was not valid JSON, rejecting")
        return Response(status_code=400)

    event = body.get("event", "")

    # The one-time handshake Zoom uses to confirm we hold the secret token
    # before it starts delivering anything real. Not signed itself.
    if event == "endpoint.url_validation":
        plain_token = body.get("payload", {}).get("plainToken", "")
        logger.info("Zoom webhook: answering endpoint.url_validation")
        return Response(
            content=json.dumps(
                build_url_validation_response(settings.zoom_webhook_secret_token, plain_token)
            ),
            media_type="application/json",
        )

    timestamp = request.headers.get("x-zm-request-timestamp", "")
    signature = request.headers.get("x-zm-signature", "")
    if not verify_signature(settings.zoom_webhook_secret_token, timestamp, raw_body, signature):
        logger.warning("Zoom webhook: signature verification failed for event=%s", event)
        return Response(status_code=401)

    if event in _RTMS_EVENTS:
        await _dispatch_rtms_event(event, body.get("payload", {}))
        return Response(status_code=200)

    logger.info("Zoom webhook: event=%s payload=%s", event, body.get("payload", {}))
    return Response(status_code=200)


async def _dispatch_rtms_event(event: str, payload: dict) -> None:
    """Never raises — a webhook handler that 500s risks Zoom's own
    retry/health-check behavior, on top of RTMSTranscriptProvider's own
    internal handling (belt-and-suspenders, not redundant: this also
    covers a lookup/dispatch bug here, not just a failure inside the
    provider). The isinstance gate covers *both* event types deliberately:
    a stray rtms_stopped reaching a Manual-active session must not call
    .stop() on it, which would silently kill that session's ability to
    accept further typed input for the rest of the meeting."""
    try:
        session = get_session(payload.get("meeting_uuid", ""))
        provider = session.manual_provider if session else None
        if not isinstance(provider, RTMSTranscriptProvider):
            logger.info(
                "Zoom webhook: %s with no active RTMS provider for meeting_uuid=%r",
                event,
                payload.get("meeting_uuid"),
            )
            return
        if event == "meeting.rtms_started":
            await provider.on_rtms_started(
                rtms_stream_id=payload.get("rtms_stream_id", ""),
                server_urls=payload.get("server_urls", ""),
            )
        else:
            await provider.stop()
    except Exception:
        logger.exception("Zoom webhook: RTMS dispatch failed for event=%s", event)
