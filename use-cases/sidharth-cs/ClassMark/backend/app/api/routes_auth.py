"""Google OAuth routes: login redirect, callback, status, logout.

The browser session cookie (set by Starlette SessionMiddleware, signed with
SESSION_SECRET) holds a session id; the tokens live server-side in the
AuthStore keyed by that id. Access tokens never reach the frontend.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.google.oauth import AuthStore, GoogleOAuth

router = APIRouter()

SESSION_COOKIE = "classroom_session"
_STATE_TTL_SECONDS = 600


def _auth(request: Request) -> tuple[GoogleOAuth, AuthStore]:
    return request.app.state.google_oauth, request.app.state.auth_store


@router.get("/api/auth/login")
async def login(request: Request) -> RedirectResponse:
    oauth, _ = _auth(request)
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    return RedirectResponse(oauth.build_auth_url(state))


@router.get("/api/auth/callback")
async def callback(code: str, state: str, request: Request) -> RedirectResponse:
    oauth, store = _auth(request)
    if not state or state != request.session.pop("oauth_state", None):
        return RedirectResponse("/?error=state_mismatch", status_code=302)
    if not code:
        return RedirectResponse("/?error=no_code", status_code=302)
    try:
        token = await oauth.exchange_code(code)
    except Exception:
        return RedirectResponse("/?error=token_exchange_failed", status_code=302)

    session_id = secrets.token_urlsafe(32)
    store.set(session_id, token)
    request.session["session_id"] = session_id
    return RedirectResponse("/", status_code=302)


@router.get("/api/auth/status")
async def status(request: Request) -> JSONResponse:
    _, store = _auth(request)
    session_id = request.session.get("session_id")
    token = await store.get(session_id) if session_id else None
    if token is None:
        return JSONResponse({"authenticated": False, "email": ""})
    return JSONResponse({"authenticated": True, "email": token.email})


@router.post("/api/auth/logout")
async def logout(request: Request) -> JSONResponse:
    _, store = _auth(request)
    session_id = request.session.pop("session_id", None)
    if session_id:
        store.delete(session_id)
    return JSONResponse({"authenticated": False})


async def require_auth(request: Request) -> str:
    """Returns a valid access token for the current session, or raises
    HTTPException(401). Every protected route calls this first."""
    from fastapi import HTTPException

    _, store = _auth(request)
    session_id = request.session.get("session_id")
    if not session_id:
        raise HTTPException(401, "not authenticated — sign in with Google first")
    token = await store.get(session_id)
    if token is None:
        raise HTTPException(401, "session expired — sign in with Google again")
    return token.access_token
