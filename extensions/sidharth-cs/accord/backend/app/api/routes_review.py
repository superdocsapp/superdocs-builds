"""Panel-facing REST surface for Milestone 5: approve the current draft,
export it, and re-download the last export. Every route lazily creates the
session via `get_or_create_session` — same idempotent pattern
routes_session.py already uses.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.api.encoding import decode_meeting_uuid
from app.drafting.session import get_or_create_session
from app.superdocs.schemas import ExportResult

router = APIRouter()

# The starter document's own <h1> is literally "Meeting Draft" — reusing
# that real text here rather than a generic "draft.docx" or a fabricated
# title this app has no real data to back (no template/title field exists
# anywhere in this codebase, confirmed — see the M5 follow-up plan).
_EXPORT_FILENAME = "Meeting-Draft.docx"


class ApproveDraftRequest(BaseModel):
    draft_version: int
    approver: str | None = None


class ExportDraftRequest(BaseModel):
    exporter: str | None = None


def _export_response(result: ExportResult) -> Response:
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={"Content-Disposition": f'attachment; filename="{_EXPORT_FILENAME}"'},
    )


@router.post("/api/meetings/{meeting_uuid}/approve")
async def approve_draft(meeting_uuid: str, body: ApproveDraftRequest, request: Request):
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    try:
        await session.approve_draft(draft_version=body.draft_version, approver=body.approver)
    except ValueError as exc:
        # The draft moved since the caller reviewed it — a conflict with
        # current server state, same 409 convention routes_session.py
        # already uses for "session isn't in the right state for this."
        raise HTTPException(409, str(exc)) from exc
    return {"approved_draft_version": body.draft_version}


@router.post("/api/meetings/{meeting_uuid}/export")
async def export_draft(meeting_uuid: str, request: Request, body: ExportDraftRequest | None = None):
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    try:
        result = await session.export_draft(exporter=body.exporter if body else None)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        # SuperDocs itself failed — the first route in this app that
        # synchronously awaits a SuperDocs call over HTTP, so there's no
        # existing precedent to reuse: 502 is the standard shape for "this
        # endpoint is fine, its upstream dependency failed." str(exc) only
        # — for the httpx.HTTPStatusError raise_for_status() raises, that
        # renders status/reason/URL, never headers, so the
        # Authorization: Bearer <SUPERDOCS_API_KEY> this client sends never
        # reaches this response.
        raise HTTPException(502, f"SuperDocs export failed: {exc}") from exc
    return _export_response(result)


@router.get("/api/meetings/{meeting_uuid}/export/download")
async def download_last_export(meeting_uuid: str, request: Request):
    """Re-serves session.last_export (session.py caches it on every
    successful export_draft() call) — no new SuperDocs call. Follow-up fix:
    a real, stable, navigable URL is what the panel's "Download document"
    link points at, rather than a one-shot JS Blob/ObjectURL the embedded
    Zoom webview may not visibly honor — a plain GET with Content-
    Disposition is the same mechanism every browser (and, plausibly, a
    Chromium-based embedded webview) already knows how to handle natively,
    with no JS download trickery required. Deliberately not gated on
    export_ready/current approval — this serves whatever was last actually
    exported, regardless of whether a newer, not-yet-approved draft exists
    since; the frontend is what decides whether to keep advertising the
    link once a newer draft makes the confirmation stale, not this route.
    Same no-new-auth posture as every other route here: the meeting_uuid
    itself is the only correlation key this app has ever used."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    if session.last_export is None:
        raise HTTPException(404, "nothing has been exported yet for this meeting")
    return _export_response(session.last_export)


class ResolveBlockingCardRequest(BaseModel):
    action: str  # "retry" | "accept" | "discard"


@router.post("/api/meetings/{meeting_uuid}/blocking-card/resolve")
async def resolve_blocking_card(meeting_uuid: str, body: ResolveBlockingCardRequest, request: Request):
    """Accept or discard an integrity-blocked batch.  'accept' commits the
    flagged changes (human override).  'discard' clears the block without
    touching the draft.  409 when no blocking card is pending."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    try:
        await session.resolve_blocking_card(action=body.action)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return session.state_snapshot()


@router.post("/api/meetings/{meeting_uuid}/retry")
async def retry_last_batch(meeting_uuid: str, request: Request):
    """Re-run the most recently failed SuperDocs batch.  409 when no failed
    batch is pending."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    try:
        await session.retry_last_batch()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return session.state_snapshot()


# --- share links ----------------------------------------------------------
#
# The assigned build's card asks for the document to be "finished and SENT
# while the call is still open... nobody has to reconcile it later". Export
# alone writes a file to the host's own disk, which reaches nobody: the host
# still emails it round afterwards, which is the reconciliation the card
# exists to eliminate.
#
# A link, not email. Sending mail needs credentials this service should not
# hold, and mail sent on someone's behalf is a much bigger thing to get wrong
# than a URL they choose to paste into the meeting chat themselves.
#
# In memory, like every other piece of session state here. A share link is
# meant to live as long as the meeting, not to become a document store — we
# edit and produce documents, we are not the archive.
_share_links: dict[str, str] = {}   # token -> meeting_uuid


def revoke_share_links(meeting_uuid: str) -> None:
    """Drop every link minted for this meeting. Called on clear so a stale
    URL cannot outlive the meeting data it points at."""
    for token in [t for t, m in _share_links.items() if m == meeting_uuid]:
        _share_links.pop(token, None)


@router.post("/api/meetings/{meeting_uuid}/share")
async def create_share_link(meeting_uuid: str, request: Request):
    """Mint an unguessable link to the APPROVED document.

    409 when nothing is approved — an unreviewed draft must never become
    shareable, which is the same invariant /export already enforces and the
    whole reason the review gate exists.
    """
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    if session.last_export is None:
        # Approved but never exported — produce the file now rather than
        # making the operator press two buttons in a live meeting.
        try:
            await session.export_draft(exporter="share link")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"SuperDocs export failed: {exc}") from exc
    token = secrets.token_urlsafe(32)
    _share_links[token] = meeting_uuid
    base = str(request.base_url).rstrip("/")
    return {"token": token, "url": f"{base}/api/share/{token}"}


@router.get("/api/share/{token}")
async def download_shared(token: str, request: Request):
    """Serve the approved document to anyone holding the link.

    Deliberately unauthenticated: the token IS the credential, and the point
    is that a participant can open it without an account during the call.
    32 bytes of urlsafe randomness is the guard.
    """
    meeting_uuid = _share_links.get(token)
    if meeting_uuid is None:
        raise HTTPException(404, "this share link is not valid")
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    if session.last_export is None:
        raise HTTPException(404, "the document behind this link is no longer available")
    return _export_response(session.last_export)
