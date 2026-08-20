"""FastAPI HTTP entrypoint for the Google Chat app.

Google Chat POSTs event JSON here and renders the JSON we return. All real logic
lives in app.dispatch (pure functions); this file only wires HTTP + dependencies,
verifies the request really came from Google Chat, and exposes a scheduler-driven
daily-digest endpoint.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from app import auth, cards
from app.config import settings
from app.dispatch import handle_event
from app.store import Store
from app.superdocs import SuperDocsClient

app = FastAPI(title="SuperDocs for Google Chat")
_store = Store()


def _client() -> SuperDocsClient:
    return SuperDocsClient(settings.superdocs_api_key)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "configured": bool(settings.superdocs_api_key),
            "auth_enforced": bool(settings.chat_audience)}


@app.post("/")
async def chat_webhook(request: Request, authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    if not auth.verify_request(authorization, settings.chat_audience):
        return JSONResponse({"text": "Unauthorized."}, status_code=401)
    event = await request.json()
    body = handle_event(
        event,
        _client(),
        _store,
        seed_template=settings.seed_template,
        export_format=settings.export_format,
    )
    return JSONResponse(body)


@app.post("/tasks/daily-digest")
async def daily_digest(request: Request) -> JSONResponse:
    """Hit by a scheduler (e.g. Cloud Scheduler) once a day. Guarded by a shared
    secret. Returns one digest card per space; a deployment with Chat service-account
    credentials also pushes each card into its space. Nothing waits silently."""
    token = request.query_params.get("token", "")
    if not settings.digest_token or token != settings.digest_token:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    digests = []
    for space in _store.spaces():
        produced, pending = _store.digest(space)
        digests.append({"space": space,
                        "card": cards.digest_card(produced=produced, pending=pending)})
    return JSONResponse({"digests": digests, "count": len(digests)})
