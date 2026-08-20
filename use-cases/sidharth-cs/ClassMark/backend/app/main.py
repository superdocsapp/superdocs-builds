"""The classroom-app backend: Google OAuth + Classroom browsing + the
native-HITL review workflow. Serves the built React frontend (frontend/
dist) at `/` — one origin, no CORS, the same choice zoom-app and Task 1
make for the same reason. The frontend must be built first
(`cd frontend && npm run build`); this module doesn't build it.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes_auth import router as auth_router
from app.api.routes_classroom import router as classroom_router
from app.api.routes_workflow import router as workflow_router
from app.core.config import get_settings
from app.google.classroom import GoogleClassroomClient
from app.google.drive import GoogleDriveClient
from app.google.oauth import AuthStore, GoogleOAuth
from app.superdocs.client import SuperDocsClient

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("classroom-app")

if not settings.google_configured:
    logger.warning(
        "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set — the OAuth "
        "flow will fail until they are."
    )
if not settings.superdocs_configured:
    logger.warning(
        "SUPERDOCS_API_KEY is not set — every SuperDocs call will fail "
        "authentication until it is."
    )
if not settings.session_secret:
    logger.warning(
        "SESSION_SECRET is not set — session cookies will be signed with a "
        "per-boot random value and every restart invalidates them."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Clients constructed here, not at module scope: httpx.AsyncClient
    # binds its connection pool to the running event loop, and module scope
    # runs before uvicorn's loop starts — the same reason zoom-app puts its
    # clients in lifespan.
    app.state.google_oauth = GoogleOAuth(
        settings.google_client_id, settings.google_client_secret, settings.google_redirect_uri
    )
    app.state.auth_store = AuthStore(app.state.google_oauth)
    app.state.classroom_client = GoogleClassroomClient()
    app.state.drive_client = GoogleDriveClient()
    app.state.superdocs_client = SuperDocsClient(
        api_key=settings.superdocs_api_key, base_url=settings.superdocs_base_url
    )
    yield
    await app.state.classroom_client.aclose()
    await app.state.drive_client.aclose()
    await app.state.superdocs_client.aclose()


app = FastAPI(title="Google Classroom Feedback — classroom-app", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or "dev-only-insecure-secret",
    session_cookie="classroom_session",
    max_age=24 * 3600,
    same_site="lax",
    https_only=False,  # localhost dev; set true behind TLS in production
)
app.include_router(auth_router)
app.include_router(classroom_router)
app.include_router(workflow_router)

_SECURITY_HEADERS = {
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
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value
    return response


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")


@app.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/", methods=["GET", "HEAD"])
def panel() -> FileResponse:
    return FileResponse(FRONTEND_DIST / "index.html")
