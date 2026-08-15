"""
Upload schemas — POST /v1/documents/upload (multipart) or
POST /v1/documents/upload-base64 (JSON) for the inline path, plus the
pre-signed large-file flow for bigger files:
  POST /v1/uploads (operationId: request_upload_url) -> {upload_id, upload_url, ...}
  PUT <upload_url>                                    -> raw bytes to cloud storage
  POST /v1/uploads/{upload_id}/process (operationId: process_uploaded_document)
       -> {session_id, filename, chunks_count, version_id, html?, ...}
All four endpoints and their exact request/response fields were fetched and
verified against docs.superdocs.app's OpenAPI fragments before this file was
written; nothing here is inferred or guessed.

Strategy threshold: the docs state the inline path (upload_document_base64)
"still works" for files under 100KB, and the pre-signed flow supports up to
100MB (`UploadUrlRequest.size_bytes` max: 104857600). Above 100KB the docs'
own guidance is to prefer the pre-signed flow — originally written for
agents avoiding LLM-context bloat, but the same threshold is a reasonable,
documented default for this connector too, since it avoids proxying large
bodies through the connector process and avoids risking any gateway body-size
limit on the inline JSON path. Callers can override via `force_presigned`.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

# Per docs.superdocs.app: "For files <100KB where token cost is trivial,
# upload_document_base64 still works inline." Above this, prefer the
# pre-signed flow (POST /v1/uploads -> PUT -> POST /v1/uploads/{id}/process).
INLINE_UPLOAD_SAFE_BYTES = 100 * 1024
# Hard ceiling per UploadUrlRequest.size_bytes' documented max (104857600 = 100MB).
PRESIGNED_UPLOAD_MAX_BYTES = 100 * 1024 * 1024


class UploadInput(BaseModel):
    filename: str = Field(..., min_length=1, max_length=512)
    content: bytes = Field(..., description="Raw file bytes. The connector chooses the inline-base64 or pre-signed-URL strategy based on len(content).")
    session_id: str | None = Field(default=None, description="Session to load the document into. If omitted, the connector mints one (uuid4).")
    content_type: str | None = Field(default=None, description="Optional MIME type override; SuperDocs primarily uses the filename extension for format detection.")
    force_presigned: bool = Field(default=False, description="Force the pre-signed upload flow even for small files (useful for testing that path).")

    @model_validator(mode="after")
    def has_extension(self) -> UploadInput:
        if "." not in self.filename:
            raise ValueError("filename must include an extension (e.g. 'contract.docx') for SuperDocs to detect the file type.")
        if len(self.content) > PRESIGNED_UPLOAD_MAX_BYTES:
            raise ValueError(
                f"File is {len(self.content)} bytes, exceeding SuperDocs' documented 100MB "
                f"({PRESIGNED_UPLOAD_MAX_BYTES} byte) cap for the pre-signed upload flow, the "
                f"largest strategy this connector supports."
            )
        return self


class UploadOutput(BaseModel):
    session_id: str
    filename: str
    strategy_used: str = Field(..., description="'inline_base64' or 'presigned_url' — which upload path the connector actually took.")
    version_id: str | None = None
    chunks_count: int | None = None
    html: str | None = Field(default=None, description="Present only if the caller requested return_html and SuperDocs returned it.")
    upload_id: str | None = Field(default=None, description="Set only for the pre-signed-flow path — the id used to reference the uploaded bytes in process_uploaded_document / export.")
    warnings: list[dict] | None = Field(default=None, description="Non-fatal parse warnings, presigned-flow only (ProcessDocumentResponse.warnings).")
