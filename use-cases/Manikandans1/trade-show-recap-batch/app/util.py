"""Small, dependency-free helpers shared across the batch generator.
Mirrors extensions/object-storage-pipeline/app/util.py — kept as a
separate copy per build so each folder stays self-contained, per the
task brief."""

from __future__ import annotations

import mimetypes
import re

# docs.superdocs.app Error Codes -> 422 Validation Error: "session_id
# may contain only letters, digits, and the characters _, -, and ., up
# to a maximum of 256 characters."
_SESSION_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_.\-]")
_SESSION_ID_MAX_LEN = 200


def sanitize_session_id(raw: str) -> str:
    cleaned = _SESSION_ID_UNSAFE.sub("-", raw)
    cleaned = cleaned.strip("-.")
    if not cleaned:
        cleaned = "session"
    return cleaned[:_SESSION_ID_MAX_LEN]


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
    return guessed or "text/plain"
