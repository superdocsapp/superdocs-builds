"""Local security gates for untrusted manuals and generated markup."""
from __future__ import annotations
import html, re
from pathlib import PurePosixPath

def sanitize_html(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", value, flags=re.I|re.S)
    value = re.sub(r"\son\w+\s*=\s*(['\"]).*?\1", "", value, flags=re.I|re.S)
    value = re.sub(r"<(iframe|object|embed)\b[^>]*>.*?</\1\s*>", "", value, flags=re.I|re.S)
    return value

def safe_filename(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or path.name != name: raise ValueError("unsafe path")
    return name

def validate_upload(name: str, size: int, content_type: str, *, max_bytes: int = 128*1024*1024) -> None:
    safe_filename(name)
    if size > max_bytes: raise ValueError("upload exceeds size limit")
    if content_type != "application/pdf" or not name.lower().endswith(".pdf"): raise ValueError("unsupported upload type")

def secret_scan(text: str) -> bool:
    return not re.search(r"(?:SUPERDOCS_API_KEY|Authorization:\s*Bearer\s+(?!\[REDACTED\])|sk-[A-Za-z0-9_-]{10,}|https?://[^\s]+/signed)", text, re.I)
