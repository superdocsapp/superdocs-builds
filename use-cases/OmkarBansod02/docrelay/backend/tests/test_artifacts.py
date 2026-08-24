import hashlib
from pathlib import Path

import pytest

from docrelay.services.artifacts import ArtifactStoreError, FilesystemArtifactStore


async def test_filesystem_artifact_survives_store_reconstruction(tmp_path: Path) -> None:
    content = b"PK\x03\x04private synthetic DOCX bytes"
    digest = hashlib.sha256(content).hexdigest()
    reference = "baselines/run-1.docx"

    await FilesystemArtifactStore(tmp_path).put(reference, content, digest)
    recovered = await FilesystemArtifactStore(tmp_path).read(reference)

    assert recovered == content
    assert (tmp_path / reference).stat().st_mode & 0o077 == 0


async def test_artifact_store_rejects_traversal_hash_mismatch_and_overwrite(
    tmp_path: Path,
) -> None:
    store = FilesystemArtifactStore(tmp_path)
    with pytest.raises(ArtifactStoreError, match="invalid artifact reference"):
        await store.put("../escape.docx", b"content", hashlib.sha256(b"content").hexdigest())
    with pytest.raises(ArtifactStoreError, match="hash"):
        await store.put("exports/run.docx", b"content", "0" * 64)

    first = b"first"
    await store.put("exports/run.docx", first, hashlib.sha256(first).hexdigest())
    second = b"second"
    with pytest.raises(ArtifactStoreError, match="different bytes"):
        await store.put("exports/run.docx", second, hashlib.sha256(second).hexdigest())
