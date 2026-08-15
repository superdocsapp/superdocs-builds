"""
generate_from_template — see schemas/generate_from_template.py's module
docstring for why this is a connector-composed operation rather than a 1:1
endpoint wrapper. Two real SuperDocs call sequences happen here depending on
the template_reference shape:
  1. (inline_base64 only) delegates to upload_document — loads the template
     bytes as the session's starting document, via whichever strategy
     (inline base64 or pre-signed URL) fits the template's size.
  2. POST /v1/chat or /v1/chat/async — the actual generation instruction.
     For `by_name` / `template_id` references, the instruction text itself
     carries the reference ("using my standard NDA template..."), since that
     is the only mechanism SuperDocs exposes for template-aware drafting.
"""
from __future__ import annotations

import base64
import uuid

from connector.http_client import SuperDocsHTTPClient
from connector.operations.upload_document import upload_document
from schemas.common import JobStatus
from schemas.generate_from_template import GenerateFromTemplateInput, GenerateFromTemplateOutput
from schemas.upload import UploadInput


def _compose_instruction(input: GenerateFromTemplateInput) -> str:
    ref = input.template_reference
    if ref.template_id is not None:
        return f"{input.instruction}\n\n(Use template id: {ref.template_id})"
    if ref.by_name is not None:
        return f"{input.instruction}\n\n(Use template: {ref.by_name})"
    # inline_base64 case: the template was already uploaded as the session's
    # document before this instruction is sent, so the instruction stands alone.
    return input.instruction


async def generate_from_template(
    client: SuperDocsHTTPClient, input: GenerateFromTemplateInput
) -> GenerateFromTemplateOutput:
    operation_id = str(uuid.uuid4())
    session_id = input.session_id or str(uuid.uuid4())
    ref = input.template_reference

    if ref.inline_base64 is not None:
        # Delegate to the standalone upload_document operation rather than
        # duplicating a raw upload call here -- one implementation of the
        # inline-vs-presigned strategy selection, exercised by its own tests.
        upload_result = await upload_document(client, UploadInput(
            filename=ref.filename or "template",
            content=base64.b64decode(ref.inline_base64),
            session_id=session_id,
        ))
        session_id = upload_result.session_id

    instruction = _compose_instruction(input)
    body = {
        "message": instruction,
        "session_id": session_id,
        "model_tier": input.model_tier.value,
        "thinking_depth": input.thinking_depth.value,
        "approval_mode": input.approval_mode.value,
        "response_mode": input.response_mode.value,
    }

    if input.run_async:
        payload = await client.post_json("/v1/chat/async", body)
        return GenerateFromTemplateOutput(
            operation_id=operation_id,
            job_id=payload["job_id"],
            session_id=payload.get("session_id", session_id),
            status=JobStatus(payload.get("status", "pending")),
        )

    payload = await client.post_json("/v1/chat", body)
    dc = payload.get("document_changes") or {}
    return GenerateFromTemplateOutput(
        operation_id=operation_id,
        job_id=None,
        session_id=payload.get("session_id", session_id),
        status=JobStatus.completed,
        version_id=dc.get("version_id"),
        updated_html=dc.get("updated_html"),
        usage=payload.get("usage"),
    )
