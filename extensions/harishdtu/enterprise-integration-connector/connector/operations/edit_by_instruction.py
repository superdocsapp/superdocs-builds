"""
edit_by_instruction — wraps POST /v1/chat (sync) and POST /v1/chat/async (async).
"""
from __future__ import annotations

import uuid

from connector.errors import ValidationError
from connector.http_client import SuperDocsHTTPClient
from schemas.common import JobStatus
from schemas.edit_by_instruction import EditByInstructionInput, EditByInstructionOutput


def _build_request_body(input: EditByInstructionInput) -> dict:
    body: dict = {
        "message": input.instruction,
        "session_id": input.session_id,
        "model_tier": input.model_tier.value,
        "thinking_depth": input.thinking_depth.value,
        "approval_mode": input.approval_mode.value,
        "response_mode": input.response_mode.value,
    }
    if input.document_html is not None:
        body["document_html"] = input.document_html
    if input.document_id is not None:
        body["document_id"] = input.document_id
    return body


async def edit_by_instruction(client: SuperDocsHTTPClient, input: EditByInstructionInput) -> EditByInstructionOutput:
    """
    Validates input, then dispatches to /v1/chat or /v1/chat/async depending
    on `input.run_async`. HITL (`approval_mode='ask_every_time'`) REQUIRES the
    async endpoint per SuperDocs' own docs — validated client-side here so a
    misconfigured recipe fails fast with a clear ValidationError instead of a
    confusing round trip to the API.
    """
    if input.approval_mode.value == "ask_every_time" and not input.run_async:
        raise ValidationError(
            "approval_mode='ask_every_time' requires run_async=True — SuperDocs' "
            "HITL flow only works over /v1/chat/async, since the job must be able "
            "to pause for approval. Set run_async=True."
        )

    operation_id = str(uuid.uuid4())
    body = _build_request_body(input)

    if input.run_async:
        payload = await client.post_json("/v1/chat/async", body)
        return EditByInstructionOutput(
            operation_id=operation_id,
            job_id=payload["job_id"],
            session_id=payload.get("session_id", input.session_id),
            status=JobStatus(payload.get("status", "pending")),
        )

    payload = await client.post_json("/v1/chat", body)
    dc = payload.get("document_changes") or {}
    return EditByInstructionOutput(
        operation_id=operation_id,
        job_id=None,
        session_id=payload.get("session_id", input.session_id),
        status=JobStatus.completed,
        changes_summary=dc.get("changes_summary"),
        version_id=dc.get("version_id"),
        updated_html=dc.get("updated_html"),
        usage=payload.get("usage"),
    )
