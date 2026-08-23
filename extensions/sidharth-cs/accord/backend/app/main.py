"""The zoom-app backend: answers Zoom's webhook handshake, and — as of
Milestone 2 — serves the real React panel (frontend/dist) at `/`. The
drafting engine and SuperDocs wiring are later milestones; the decisions
behind them are logged in PROGRESS.md at the repository root.

Serves the API and the panel from a single origin, the same choice Task 1
makes for the same reason: no CORS, no second process for someone to start.

M0's static spike page still lives at /static/panel.html for reference —
not deleted, just no longer what `/` serves. The frontend must be built
first (`cd frontend && npm run build`); this module doesn't build it.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_events import router as events_router
from app.api.routes_listen import router as listen_router
from app.api.routes_review import router as review_router
from app.api.routes_audio import router as audio_router
from app.api.routes_audio_test import router as audio_test_router
from app.api.routes_helper import router as helper_router
from app.api.routes_session import router as session_router
from app.core.config import get_settings
from app.superdocs.client import SuperDocsClient
from app.zoom.webhooks import router as zoom_webhooks_router

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("zoom-app")

if not settings.zoom_webhook_secret_token:
    logger.warning(
        "ZOOM_WEBHOOK_SECRET_TOKEN is not set — the url_validation handshake "
        "and every subsequent webhook will fail verification until it is."
    )
if not settings.superdocs_api_key:
    logger.warning(
        "SUPERDOCS_API_KEY is not set — every drafting call will fail "
        "authentication until it is."
    )
if settings.transcript_provider == "vexa" and not (
    settings.vexa_api_base_url and settings.vexa_api_key
):
    logger.warning(
        "TRANSCRIPT_PROVIDER=vexa but VEXA_API_BASE_URL/VEXA_API_KEY are not "
        "both set — Start listening will report live transcription unavailable; "
        "manual input remains available."
    )
if settings.transcript_provider == "rtms" and not (
    settings.zoom_client_id and settings.zoom_client_secret
):
    logger.warning(
        "TRANSCRIPT_PROVIDER=rtms but ZOOM_CLIENT_ID/ZOOM_CLIENT_SECRET are "
        "not both set — sessions will fall back to ManualTranscriptProvider."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Constructed here, not at module scope: httpx.AsyncClient (via httpcore)
    # binds internal connection-pool primitives to whatever event loop is
    # running at construction time. Module scope runs at import, before
    # uvicorn's loop starts — the client silently hangs on first real request
    # (no exception, no socket ever opened) because its pool is bound to the
    # wrong loop. `lifespan` runs inside the actual serving loop, same reason
    # FastAPI's own docs put DB pools/HTTP clients here instead of at import.
    app.state.superdocs_client = SuperDocsClient(
        api_key=settings.superdocs_api_key, base_url=settings.superdocs_base_url
    )
    yield
    await app.state.superdocs_client.aclose()


app = FastAPI(title="Live Deliverable — zoom-app", lifespan=lifespan)


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError) -> Response:
    # Turn ValueErrors from encoding/decode utilities into proper 422s
    # rather than bare 500s.  Specifically: malformed meeting UUIDs raise
    # ValueError from decode_meeting_uuid (encoding.py).
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": str(exc)})
# One client for the process lifetime, reused across meetings/sessions — the
# same shape as Task 1's own single-client-instance convention. Stashed on
# app.state, not a module-level global, so routes reach it via `request.app`
# (FastAPI's own recommended pattern) rather than importing main from api/.
app.include_router(zoom_webhooks_router)
app.include_router(audio_router)
app.include_router(audio_test_router)
app.include_router(session_router)
app.include_router(events_router)
app.include_router(review_router)
app.include_router(listen_router)
app.include_router(helper_router)

# Zoom's client refuses to render ANY html document response that's missing
# these — not a style choice. frame-ancestors is deliberately left unset:
# Zoom's docs require the header to be *present* but don't publish what
# origin their embedding webview actually uses, and a guessed value risks
# silently blocking the one thing this page has to do.
#
# script-src tightened to 'self' only as of M2 — the M0 spike loaded
# @zoom/appssdk from Zoom's CDN (hence the external allowance this comment
# used to note), but the real panel imports it as an npm dependency, so
# Vite bundles it straight into the built JS. Nothing external to allow.
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "connect-src 'self'; "
        "base-uri 'none'; "
        "form-action 'none'"
    ),
}


@app.middleware("http")
async def add_owasp_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        # Skip if the route already set this header (e.g. /audio-test
        # overrides CSP to permit its inline diagnostic script).
        if name not in response.headers:
            response.headers[name] = value
    return response

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# zoom-app/frontend/dist — built separately (`cd frontend && npm run
# build`), not by this process. Mounted at /assets rather than / itself so
# it can't shadow /health and /webhooks/zoom with a catch-all match; only
# the panel() route below serves index.html.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")


@app.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict[str, str]:
    return {"status": "ok"}



@app.api_route("/", methods=["GET", "HEAD"])
def panel() -> FileResponse:
    # HEAD, not just GET: Zoom's Home URL reachability check uses HEAD.
    # Cache-Control: no-cache forces the Zoom webview to revalidate
    # index.html on every load, so new JS bundles (content-hashed by
    # Vite) are always discovered.
    return FileResponse(
        FRONTEND_DIST / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
