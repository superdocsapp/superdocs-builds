"""The one place that branches on TRANSCRIPT_PROVIDER — Milestone 4. A plain
function, not a class: it holds no state, matching this codebase's existing
preference for stateless functions over classes for this shape of logic
(classifier.py's classify/build_instruction). Deliberately can't live in
provider.py: that file's own docstring states "Nothing below imports either
concrete provider," and this function has to import both.

The only branch is here, once, at session-creation time — see
drafting/session.py::get_or_create_session, the sole call site.
"""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.transcript.manual_provider import ManualTranscriptProvider
from app.transcript.provider import TranscriptProvider
from app.transcript.rtms_provider import RTMSTranscriptProvider
from app.transcript.vexa_provider import VexaTranscriptProvider

logger = logging.getLogger("transcript.factory")


def create_transcript_provider(settings: Settings) -> TranscriptProvider:
    if settings.transcript_provider == "vexa":
        # Unconfigured Vexa (blank base URL or key) is NOT a factory-time
        # fallback: the provider still constructs so the session's provider
        # identity stays honest ("vexa" + degraded at begin_listening), and
        # manual input stays open through its submit(). The panel shows
        # "Live transcription unavailable" rather than silently pretending
        # another provider is active.
        return VexaTranscriptProvider(
            settings.vexa_api_base_url,
            settings.vexa_api_key,
            bot_name=settings.vexa_bot_name,
            language=settings.vexa_language,
            poll_interval_seconds=settings.vexa_poll_interval_seconds,
        )

    if settings.transcript_provider == "rtms":
        if settings.zoom_client_id and settings.zoom_client_secret:
            return RTMSTranscriptProvider(settings.zoom_client_id, settings.zoom_client_secret)
        logger.warning(
            "TRANSCRIPT_PROVIDER=rtms but ZOOM_CLIENT_ID/ZOOM_CLIENT_SECRET are not both "
            "set — falling back to ManualTranscriptProvider."
        )
        return ManualTranscriptProvider()

    if settings.transcript_provider != "manual":
        logger.warning(
            "TRANSCRIPT_PROVIDER=%r is not recognized (expected 'vexa', 'manual' or "
            "'rtms') — falling back to ManualTranscriptProvider.",
            settings.transcript_provider,
        )

    return ManualTranscriptProvider()
