import asyncio
import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol


class ArtifactStoreError(RuntimeError):
    pass


class ArtifactStore(Protocol):
    async def put(self, reference: str, content: bytes, expected_sha256: str) -> None: ...

    async def read(self, reference: str) -> bytes: ...


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}

    async def put(self, reference: str, content: bytes, expected_sha256: str) -> None:
        _require_reference(reference)
        _require_hash(content, expected_sha256)
        current = self._items.get(reference)
        if current is not None and current != content:
            raise ArtifactStoreError("artifact reference already contains different bytes")
        self._items[reference] = bytes(content)

    async def read(self, reference: str) -> bytes:
        _require_reference(reference)
        try:
            return self._items[reference]
        except KeyError as exc:
            raise ArtifactStoreError("artifact does not exist") from exc


class FilesystemArtifactStore:
    """Private local artifact store with deterministic references and atomic writes."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put(self, reference: str, content: bytes, expected_sha256: str) -> None:
        _require_reference(reference)
        _require_hash(content, expected_sha256)
        await asyncio.to_thread(self._put_sync, reference, content)

    async def read(self, reference: str) -> bytes:
        _require_reference(reference)
        return await asyncio.to_thread(self._read_sync, reference)

    def _put_sync(self, reference: str, content: bytes) -> None:
        target = self._path(reference)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.exists():
            existing = target.read_bytes()
            if existing != content:
                raise ArtifactStoreError("artifact reference already contains different bytes")
            return
        descriptor, temporary_name = tempfile.mkstemp(prefix=".docrelay-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _read_sync(self, reference: str) -> bytes:
        path = self._path(reference)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactStoreError("artifact does not exist") from exc

    def _path(self, reference: str) -> Path:
        target = (self._root / PurePosixPath(reference)).resolve()
        if not target.is_relative_to(self._root):
            raise ArtifactStoreError("artifact reference escaped the configured root")
        return target


def _require_reference(reference: str) -> None:
    path = PurePosixPath(reference)
    if (
        not reference
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
    ):
        raise ArtifactStoreError("invalid artifact reference")


def _require_hash(content: bytes, expected_sha256: str) -> None:
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ArtifactStoreError("artifact hash does not match the expected identity")
