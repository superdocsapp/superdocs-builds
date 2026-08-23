"""Panel-facing REST surface for Milestone 3: submit transcript text, read
current session state. Both routes lazily create the session via
`get_or_create_session` — idempotent, so calling it from either route (or
both, in either order) is safe; there's no separate "init" step for the
manual-entry path (design doc §4's Setup screen is not part of M3's scope).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.encoding import decode_meeting_uuid
from app.api.routes_review import revoke_share_links
from app.drafting.session import get_or_create_session

router = APIRouter()


class SubmitTranscriptRequest(BaseModel):
    text: str
    speaker: str | None = None
    is_correction: bool = False


@router.post("/api/meetings/{meeting_uuid}/transcript")
async def submit_transcript(meeting_uuid: str, body: SubmitTranscriptRequest, request: Request):
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    if session.manual_provider is None:
        # Not reachable in M3 (the registry always constructs Manual), but
        # the check stays honest for when a non-Manual provider can be
        # active — see session.py's own comment on why this attribute
        # exists separately from the Protocol.
        raise HTTPException(409, "the active transcript provider does not accept manual input")
    try:
        event = await session.manual_provider.submit(body.text, body.speaker, is_correction=body.is_correction)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"sequence": event.sequence}


@router.get("/api/meetings/{meeting_uuid}/state")
async def get_state(meeting_uuid: str, request: Request):
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    return session.state_snapshot()


@router.post("/api/meetings/{meeting_uuid}/clear")
async def clear_meeting_data(meeting_uuid: str, request: Request):
    """Reset transcript, activity, draft, and review/export state.  Does NOT
    stop listening or clear credentials.  Idempotent — calling it twice is
    safe.  Returns the cleared state snapshot."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    await session.reset()
    # A share link points at a document that no longer exists once the
    # meeting is cleared. Revoke it here rather than leaving a URL that
    # serves stale content to whoever still has it.
    revoke_share_links(meeting_uuid)
    return session.state_snapshot()


class SetTemplateRequest(BaseModel):
    template_key: str
    topic: str | None = None
    client: str | None = None
    prepared_by: str | None = None


@router.get("/api/templates")
async def list_templates():
    """Return the available starter templates with labels and descriptions."""
    from app.drafting.templates import list_templates
    return list_templates()


class UploadTemplateRequest(BaseModel):
    """The firm's own .docx, base64-encoded."""
    file_base64: str
    filename: str = "template.docx"


@router.post("/api/meetings/{meeting_uuid}/template/upload")
async def upload_template(meeting_uuid: str, body: UploadTemplateRequest, request: Request):
    """Use the firm's own document as the starting point instead of one of
    the built-in templates — the brief's "on the firm's template"."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    try:
        await session.set_custom_template(
            file_base64=body.file_base64, filename=body.filename
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"could not read that document: {exc}") from exc
    return session.state_snapshot()


@router.post("/api/meetings/{meeting_uuid}/template")
async def set_template(meeting_uuid: str, body: SetTemplateRequest, request: Request):
    """Set the active template for this meeting.  Re-renders the starter
    document with meeting metadata if no draft exists yet."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    try:
        await session.set_active_template(
            key=body.template_key,
            topic=body.topic or "",
            client=body.client or "",
            prepared_by=body.prepared_by or "",
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return session.state_snapshot()


# ---- Phase 3: Multi-document -----------------------------------------------

class CreateDocumentRequest(BaseModel):
    template_key: str | None = None


@router.post("/api/meetings/{meeting_uuid}/documents")
async def create_document(meeting_uuid: str, body: CreateDocumentRequest | None = None, request: Request = None):
    """Create a new document and make it active."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    from app.drafting.templates import SOW
    key = (body.template_key if body else None) or SOW
    await session.create_document(template_key=key)
    return session.state_snapshot()


@router.post("/api/meetings/{meeting_uuid}/documents/{document_id}/activate")
async def activate_document(meeting_uuid: str, document_id: str, request: Request):
    """Switch to a different document."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    try:
        await session.activate_document(document_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return session.state_snapshot()


@router.delete("/api/meetings/{meeting_uuid}/documents/{document_id}")
async def delete_document(meeting_uuid: str, document_id: str, request: Request):
    """Delete a document.  409 if it's the last document."""
    meeting_uuid = decode_meeting_uuid(meeting_uuid)
    session = await get_or_create_session(meeting_uuid, request.app.state.superdocs_client)
    try:
        await session.delete_document(document_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return session.state_snapshot()
