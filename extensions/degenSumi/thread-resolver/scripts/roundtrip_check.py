"""Checks what survives a round trip through the editing service.

A .docx carries comment threads across three parts, and only one of them holds
reply parentage and resolved state. This script uploads a document, exports it
back, and reports which of those parts came back intact.

The answer decides how approved edits are applied. If thread structure survives,
the exported file can be used directly. If it does not, the export cannot be the
deliverable, because it would drop threads the run never touched.

Run:
    uv run python scripts/roundtrip_check.py out/mixed_document.docx
"""

from __future__ import annotations

import base64
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import httpx

from thread_resolver.adapters.docx_source import DocxThreadSource
from thread_resolver.adapters.ooxml import (
    COMMENTS_EXTENDED_PART,
    COMMENTS_PART,
    DOCUMENT_PART,
)
from thread_resolver.config import Settings

TIMEOUT = 180.0


def parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def describe(path: Path, data: bytes) -> None:
    threads = DocxThreadSource(data, path.name).read_threads()
    print(f"  parts:    {len(parts(data))}")
    print(f"  threads:  {len(threads)}")
    print(f"  replies:  {sum(len(t.replies) for t in threads)}")
    print(f"  resolved: {sum(1 for t in threads if t.resolved)}")


def main(source: Path) -> int:
    settings = Settings()
    key = settings.require_superdocs_key()
    client = httpx.Client(
        base_url=settings.superdocs_base_url,
        headers={"Authorization": f"Bearer {key}"},
        timeout=TIMEOUT,
    )

    original = source.read_bytes()
    session_id = f"roundtrip-check-{source.stem}"

    print(f"before  {source.name}")
    describe(source, original)

    upload = client.post(
        "/v1/documents/upload-base64",
        json={
            "filename": source.name,
            "file_base64": base64.b64encode(original).decode(),
            "session_id": session_id,
        },
    )
    if upload.status_code != 200:
        print(f"\nupload failed: {upload.status_code} {upload.text[:300]}")
        return 1
    print(f"\nuploaded: {str(upload.json())[:200]}")

    export = client.post(
        "/v1/documents/export",
        json={"session_id": session_id, "format": "docx", "source_filename": source.name},
    )
    if export.status_code != 200:
        print(f"\nexport failed: {export.status_code} {export.text[:300]}")
        return 1

    exported = export.content
    if exported[:2] != b"PK":
        print(f"\nexport was not a zip; first bytes: {exported[:60]!r}")
        return 1

    out = Path("out") / f"roundtrip-{source.name}"
    out.write_bytes(exported)

    print(f"\nafter   {out}")
    describe(out, exported)

    before, after = parts(original), parts(exported)
    print("\npart-by-part")
    for name in (DOCUMENT_PART, COMMENTS_PART, COMMENTS_EXTENDED_PART):
        if name not in after:
            print(f"  {name:34} DROPPED")
        elif before.get(name) == after[name]:
            print(f"  {name:34} identical")
        else:
            sizes = f"{len(before.get(name, b''))} -> {len(after[name])} bytes"
            print(f"  {name:34} present, changed ({sizes})")

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    if added:
        print(f"  added parts:   {added}")
    if removed:
        print(f"  removed parts: {removed}")

    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("out/mixed_document.docx")
    raise SystemExit(main(target))
