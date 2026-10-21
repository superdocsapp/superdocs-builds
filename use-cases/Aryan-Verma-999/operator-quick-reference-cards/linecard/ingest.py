"""Immutable, local-only PDF ingestion and evidence records.

The parser never fetches URLs and never sends source bytes to a model.  OCR is
intentionally unsupported: exact-value evidence must come from native PDF text.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

MAGIC = b"%PDF-"
PARSER_VERSION = "linecard-pdf-ingest-v1"


class IngestBlocked(ValueError):
    pass


def stream_hash(stream: BinaryIO, chunk_size: int = 1024 * 1024) -> tuple[str, int, bytes]:
    digest = hashlib.sha256(); size = 0; prefix = b""
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        if len(prefix) < 16:
            prefix += chunk[: 16 - len(prefix)]
        digest.update(chunk); size += len(chunk)
    return digest.hexdigest(), size, prefix


def validate_pdf(path: Path, *, max_bytes: int = 128 * 1024 * 1024) -> dict[str, Any]:
    with path.open("rb") as fh:
        sha, size, prefix = stream_hash(fh)
    if size > max_bytes:
        raise IngestBlocked(f"upload exceeds {max_bytes} byte limit")
    if prefix != MAGIC and not prefix.startswith(MAGIC):
        raise IngestBlocked("MIME/magic validation failed: expected PDF")
    return {"path": str(path), "sha256": sha, "byte_size": size, "mime": "application/pdf", "magic": prefix.decode("latin1")}


def _page_record(page: Any, index: int) -> dict[str, Any]:
    text = page.get_text("text")
    words = []
    for word in page.get_text("words"):
        words.append({"x0": word[0], "y0": word[1], "x1": word[2], "y1": word[3], "text": word[4], "block": word[5], "line": word[6], "word": word[7]})
    drawings = page.get_drawings()
    images = page.get_images(full=True)
    return {
        "pdf_index": index, "physical_page_number": index + 1,
        "printed_page_label": None, "width": page.rect.width, "height": page.rect.height,
        "rotation": page.rotation, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "words": words, "spans": page.get_text("dict").get("blocks", []),
        "font_signals": sorted({s.get("font", "") for b in page.get_text("dict").get("blocks", []) for l in b.get("lines", []) for s in l.get("spans", [])}),
        "image_count": len(images), "image_coverage": 0.0, "drawing_count": len(drawings),
        "annotations": [a.type for a in page.annots() or []],
        "native_text": bool(text.strip()),
    }


def ingest_pdf(path: str | Path, *, max_pages: int = 5000, max_bytes: int = 128 * 1024 * 1024) -> dict[str, Any]:
    path = Path(path); meta = validate_pdf(path, max_bytes=max_bytes)
    try:
        import fitz
    except ImportError as exc:
        raise IngestBlocked("PyMuPDF is required for PDF ingestion") from exc
    raw = path.read_bytes()
    doc = fitz.open(stream=raw, filetype="pdf")
    if doc.is_encrypted:
        raise IngestBlocked("encrypted PDFs are unsupported without an explicit reviewed decrypt path")
    if len(doc) > max_pages:
        raise IngestBlocked(f"page count exceeds {max_pages}")
    pages = [_page_record(page, i) for i, page in enumerate(doc)]
    repeated = {}
    for key in ("header", "footer"):
        repeated[key] = []
    if pages:
        first_lines = [x.strip() for x in pages[0]["text"].splitlines() if x.strip()]
        last_lines = [x.strip() for x in pages[0]["text"].splitlines() if x.strip()]
        for line in first_lines[:2]:
            if sum(line in p["text"] for p in pages) >= max(2, len(pages) // 3): repeated["header"].append(line)
        for line in last_lines[-2:]:
            if sum(line in p["text"] for p in pages) >= max(2, len(pages) // 3): repeated["footer"].append(line)
    return {**meta, "schema": "linecard-extraction-manifest-v1", "parser_version": PARSER_VERSION,
            "page_count": len(pages), "pages": pages, "repeated_header_footer": repeated,
            "encrypted": False, "ocr": False}


def save_manifest(manifest: dict[str, Any], path: str | Path) -> None:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False); fh.write("\n"); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
