"""Runtime configuration.

Grows one field at a time, only when a milestone's code actually reads it —
see zoom-app/PROGRESS.md.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored, not relative: `.env` lives at the zoom-app/ root, four levels up
# from this file (core -> app -> backend -> zoom-app). A relative "​.env"
# resolves against the process's cwd instead, which differs by entry point
# (Makefile targets `cd backend` first; a manually-launched uvicorn might
# not) — found the hard way when `make smoke` reported the real
# SUPERDOCS_API_KEY as unset despite it being in .env.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # From the Zoom Marketplace app's Feature > Access > Event Subscriptions
    # page. Required to verify webhook signatures and to answer the
    # endpoint.url_validation handshake — see app/zoom/webhooks.py.
    zoom_webhook_secret_token: str = ""

    # From docs.superdocs.app account settings, created via
    # POST /v1/users/me/api-keys. Never printed, logged, or sent anywhere
    # except api.superdocs.app — see app/superdocs/client.py.
    superdocs_api_key: str = ""
    superdocs_base_url: str = "https://api.superdocs.app"

    # Milestone 4/6 — which TranscriptProvider get_or_create_session builds.
    # "vexa" is the default (Milestone 6): live transcription via the Vexa
    # meeting-bot API. "manual" is the fallback (development, debugging,
    # environments where Vexa is unavailable). "rtms" is supported for the
    # moment the platform grants it (confirmed unavailable on this account,
    # PROGRESS.md M0). See app/transcript/factory.py.
    transcript_provider: str = "vexa"

    # Milestone 6 — Vexa live transcription. Vexa's one job in this app:
    # join the Zoom meeting as a bot and deliver transcript data; every-
    # thing after ingestion is the existing Draft Engine's. Base URL of the
    # Vexa API gateway (self-hosted gateway, or the hosted API when Zoom is
    # supported there) and the gateway's X-API-Key. If either is blank the
    # provider still constructs — listening degrades to "Live transcription
    # unavailable" and manual input stays open; the app never crashes on
    # missing config. See app/transcript/vexa_provider.py.
    vexa_api_base_url: str = ""
    vexa_api_key: str = ""
    vexa_bot_name: str = "Live Deliverable"
    vexa_language: str = "en"
    vexa_poll_interval_seconds: float = 3.0

    # The Marketplace app's OAuth Client ID/Secret (App Credentials page) —
    # distinct from zoom_webhook_secret_token above. Required only when
    # transcript_provider="rtms": signs the RTMS websocket handshake, see
    # app/core/security.py::build_rtms_signature.
    zoom_client_id: str = ""
    zoom_client_secret: str = ""

    # Groq STT API key — used by the local audio capture path
    # (routes_audio.py).  Server-side only; never exposed to frontend or
    # Swift capture helper.
    groq_api_key: str = ""

    # Shared secret for the Mac capture-helper's outbound WSS connection.
    # The helper authenticates with this on the /ws/helper handshake so the
    # WebSocket is not a public, unauthenticated command channel. Blank → the
    # helper endpoint is disabled (connections rejected).
    helper_auth_token: str = ""

    # SuperDocs AI editing configuration. Omitted (None) → the server's
    # defaults (core + balanced) apply — the casual-editing default.
    # The model-selection docs recommend core/max + deep for multi-section
    # document drafting; the M1-M6 experiment measures whether that holds.
    superdocs_model_tier: str | None = None
    superdocs_thinking_depth: str | None = None

    # When False, instructions stop naming a target section and every batch
    # goes out as "add these facts to the most appropriate section" — the
    # platform decides placement instead of our heading rules. Kept as a
    # switch rather than a deletion so the two can be compared on the same
    # audio: heading routing is what makes placement deterministic and what
    # the post-edit placement check verifies against, so turning it off
    # trades that guarantee for whatever the platform picks.
    # Turned off once as an experiment and turned straight back on: with the
    # platform choosing placement, dates landed under Scope of Work, and
    # Deliverables and Budget were denied outright with "nothing actually
    # changed" — heading routing is what makes placement deterministic and
    # is what the post-edit placement check verifies against.
    section_targeting: bool = True

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
