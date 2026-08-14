"""Uploads are streamed to disk in chunks and size-capped mid-stream."""

from __future__ import annotations

import io
import uuid

import pytest
from starlette.datastructures import Headers, UploadFile

from app.services.storage import stream_upload_to_disk
from tests.helpers import count_documents


@pytest.mark.asyncio
async def test_stream_writes_file_in_small_chunks(tmp_path):
    payload = b"0123456789abcdef"  # 16 bytes
    upload = UploadFile(
        filename="sample.txt",
        file=io.BytesIO(payload),
        headers=Headers({"content-type": "text/plain"}),
    )

    stored = await stream_upload_to_disk(
        upload,
        upload_dir=str(tmp_path),
        tenant_id=uuid.uuid4(),
        chunk_size=4,  # forces multiple read/write iterations
        max_bytes=1024,
    )

    assert stored.size_bytes == len(payload)
    with open(stored.path, "rb") as fh:
        assert fh.read() == payload


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected_and_not_persisted(client, make_tenant, settings, sessionmaker):
    tenant_id, headers = await make_tenant()
    original = settings.max_upload_bytes
    settings.max_upload_bytes = 8  # tiny cap for the test
    try:
        files = {"file": ("big.bin", b"way more than eight bytes", "application/octet-stream")}
        resp = await client.post(
            "/v1/documents", files=files, headers={**headers, "Idempotency-Key": uuid.uuid4().hex}
        )
        assert resp.status_code == 413
        # Rejected before any DB record was created.
        assert await count_documents(sessionmaker, tenant_id) == 0
    finally:
        settings.max_upload_bytes = original
