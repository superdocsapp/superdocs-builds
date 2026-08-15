"""
upload_document — the standalone typed upload operation (Section 3 of the
brief). Selects a strategy by file size rather than blindly base64-encoding
everything:

  <= INLINE_UPLOAD_SAFE_BYTES (100KB, per docs.superdocs.app's own stated
     safe-inline threshold): POST /v1/documents/upload-base64 (JSON, one call).

  >  INLINE_UPLOAD_SAFE_BYTES, up to PRESIGNED_UPLOAD_MAX_BYTES (100MB):
     1. POST /v1/uploads              -> {upload_id, upload_url, ...}
     2. PUT  upload_url               -> raw bytes to cloud storage (no SuperDocs auth header)
     3. POST /v1/uploads/{id}/process -> {session_id, filename, chunks_count, version_id, ...}

`force_presigned=True` routes through the second path regardless of size,
mainly for exercising/testing that path deterministically.
"""
from __future__ import annotations

import base64
import mimetypes
import uuid

from connector.errors import UnsupportedFormatError
from connector.http_client import SuperDocsHTTPClient
from schemas.common import SUPPORTED_UPLOAD_EXTENSIONS
from schemas.upload import INLINE_UPLOAD_SAFE_BYTES, UploadInput, UploadOutput


def _extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _guess_content_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _validate_extension(filename: str) -> None:
    ext = _extension_of(filename)
    if ext not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported file type: .{ext or '?'}. Supported: {', '.join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))}. "
            f"Legacy .doc must be converted to .docx before upload.",
            status_code=None, detail=f"unsupported extension .{ext}",
        )


async def _upload_inline(client: SuperDocsHTTPClient, input: UploadInput, session_id: str) -> UploadOutput:
    payload = await client.post_json("/v1/documents/upload-base64", {
        "filename": input.filename,
        "file_base64": base64.b64encode(input.content).decode("ascii"),
        "session_id": session_id,
    })
    return UploadOutput(
        session_id=payload.get("session_id", session_id),
        filename=input.filename,
        strategy_used="inline_base64",
        version_id=payload.get("version_id"),
        chunks_count=payload.get("chunks_count"),
        html=payload.get("html"),
        upload_id=None,
        warnings=None,
    )


async def _upload_presigned(client: SuperDocsHTTPClient, input: UploadInput, session_id: str) -> UploadOutput:
    content_type = input.content_type or _guess_content_type(input.filename)

    url_payload = await client.post_json("/v1/uploads", {
        "filename": input.filename,
        "content_type": content_type,
        "size_bytes": len(input.content),
        "purpose": "document",
    })
    upload_id = url_payload["upload_id"]
    upload_url = url_payload["upload_url"]

    await client.put_presigned(upload_url, input.content, content_type=content_type)

    process_payload = await client.post_json(f"/v1/uploads/{upload_id}/process", {
        "session_id": session_id,
        "filename": input.filename,
        "parse_mode": "document",
    })
    return UploadOutput(
        session_id=process_payload.get("session_id", session_id),
        filename=process_payload.get("filename", input.filename),
        strategy_used="presigned_url",
        version_id=process_payload.get("version_id"),
        chunks_count=process_payload.get("chunks_count"),
        html=process_payload.get("html"),
        upload_id=upload_id,
        warnings=process_payload.get("warnings"),
    )


async def upload_document(client: SuperDocsHTTPClient, input: UploadInput) -> UploadOutput:
    _validate_extension(input.filename)
    session_id = input.session_id or str(uuid.uuid4())

    use_presigned = input.force_presigned or len(input.content) > INLINE_UPLOAD_SAFE_BYTES
    if use_presigned:
        return await _upload_presigned(client, input, session_id)
    return await _upload_inline(client, input, session_id)
