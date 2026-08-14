"""File storage: stream uploads to disk in CHUNKS, never into memory.

Why: a 50 MiB (or larger) document loaded fully into RAM per concurrent upload
is a trivial denial-of-service. We read a bounded chunk, write it, and enforce
the size cap AS WE GO — so an oversized upload is rejected without ever being
fully buffered, and the partial file is cleaned up.

Files are namespaced per tenant on disk as defense-in-depth on top of the DB
tenant scoping.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass

import aiofiles
from fastapi import HTTPException, status
from starlette.datastructures import UploadFile

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


@dataclass
class StoredFile:
    path: str
    size_bytes: int
    filename: str
    content_type: str


def _sanitize_filename(name: str | None) -> str:
    base = os.path.basename(name or "upload.bin")
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "upload.bin"
    return cleaned[:255]


async def stream_upload_to_disk(
    upload: UploadFile,
    *,
    upload_dir: str,
    tenant_id: uuid.UUID,
    chunk_size: int,
    max_bytes: int,
) -> StoredFile:
    filename = _sanitize_filename(upload.filename)
    tenant_dir = os.path.join(upload_dir, str(tenant_id))
    os.makedirs(tenant_dir, exist_ok=True)
    # Unique on-disk name prevents collisions and path guessing.
    dest_path = os.path.join(tenant_dir, f"{uuid.uuid4().hex}_{filename}")

    size = 0
    try:
        async with aiofiles.open(dest_path, "wb") as out:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    # Stop immediately; do not keep reading an oversized stream.
                    await out.close()
                    _safe_unlink(dest_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Upload exceeds max size of {max_bytes} bytes.",
                    )
                await out.write(chunk)
    except HTTPException:
        raise
    except Exception:
        _safe_unlink(dest_path)
        raise

    if size == 0:
        _safe_unlink(dest_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty upload."
        )

    return StoredFile(
        path=dest_path,
        size_bytes=size,
        filename=filename,
        content_type=upload.content_type or "application/octet-stream",
    )


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
