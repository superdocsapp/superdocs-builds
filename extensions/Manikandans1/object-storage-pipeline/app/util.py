"""Small, dependency-free helpers shared across the pipeline.

Nothing here talks to SuperDocs or S3 directly — it's pure string/format
logic, kept separate so it's trivially unit-testable and so
`superdocs_client.py` / `s3_client.py` stay focused on their own jobs.
"""

from __future__ import annotations

import mimetypes
import re

# SuperDocs' documented rule (Error Codes -> 422 Validation Error):
# "session_id may contain only letters, digits, and the characters _, -,
# and ., up to a maximum of 256 characters." We build session ids out of
# S3 keys, which can contain slashes, spaces, and unicode — so every
# session id this pipeline sends is passed through here first.
_SESSION_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_.\-]")
_SESSION_ID_MAX_LEN = 200  # comfortably under the documented 256 cap


def sanitize_session_id(raw: str) -> str:
    cleaned = _SESSION_ID_UNSAFE.sub("-", raw)
    cleaned = cleaned.strip("-.")
    if not cleaned:
        cleaned = "session"
    return cleaned[:_SESSION_ID_MAX_LEN]


# Formats SuperDocs' /v1/documents/upload endpoint accepts, per
# docs.superdocs.app/concepts/documents#loading-documents-from-files:
# "Supported formats: DOCX, DOC, ODT, PDF, TXT, HTML, MD (Markdown), RTF"
SUPPORTED_UPLOAD_EXTENSIONS = {
    ".docx", ".doc", ".odt", ".pdf", ".txt", ".html", ".htm", ".md", ".rtf",
}

# Formats /v1/documents/export accepts, per
# docs.superdocs.app/concepts/documents#exporting-documents.
SUPPORTED_EXPORT_FORMATS = {"docx", "pdf", "html", "markdown", "txt"}

_EXPORT_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html",
    "markdown": "text/markdown",
    "txt": "text/plain",
}


def content_type_for_export_format(export_format: str) -> str:
    return _EXPORT_CONTENT_TYPES.get(export_format, "application/octet-stream")


def guess_content_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def is_supported_upload_extension(filename: str) -> bool:
    for ext in SUPPORTED_UPLOAD_EXTENSIONS:
        if filename.lower().endswith(ext):
            return True
    return False
