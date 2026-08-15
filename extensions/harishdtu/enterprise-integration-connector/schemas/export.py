from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from schemas.common import ExportFormat, ExportOptions


class ExportInput(BaseModel):
    html: str | None = Field(default=None, description="Inline HTML to export ad-hoc (<=20MB).")
    session_id: str | None = Field(default=None, description="Export the current state of this session's document.")
    upload_id: str | None = Field(default=None, description="Pre-signed-upload reference, for documents 20-100MB.")
    format: ExportFormat = ExportFormat.docx
    filename: str | None = None
    options: ExportOptions | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> ExportInput:
        provided = sum([self.html is not None, self.session_id is not None, self.upload_id is not None])
        if provided != 1:
            raise ValueError("ExportInput requires exactly one of: html, session_id, or upload_id.")
        return self


class ExportWarningEntry(BaseModel):
    """One entry from the X-Export-Warnings response header. Non-fatal by
    definition — an export with warnings is still a successful export."""
    code: str
    message: str | None = None
    detail: dict | None = None


class ExportOutput(BaseModel):
    format: ExportFormat
    filename: str | None = None
    content_type: str
    content_base64: str = Field(..., description="Binary export content, base64-encoded for transport through JSON-oriented platform connector SDKs.")
    size_bytes: int
    warnings: list[ExportWarningEntry] = Field(default_factory=list, description=(
        "Non-fatal issues from X-Export-Warnings (e.g. image_download_failed). "
        "MUST NOT be treated as a failure — export succeeded, this is informational."
    ))
