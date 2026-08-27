"""Where photograph bytes actually live.

They used to live in Postgres as `BYTEA`. That is transactional and it is why the whole
application ran from one `docker compose up`, but it puts hundreds of gigabytes a year into
the database for a firm doing five inspections a day — and every backup, every restore and
every replica carries them.

So the bytes move to a blob store and the database keeps a key. The store is a seam rather
than a vendor: a filesystem implementation ships and backs the default deployment, and S3 or
GCS is a class satisfying the same three methods, not a change to anything above it.

**Keys are content hashes.** The build already treats a photograph's sha256 as its identity —
the same bytes are the same photograph, however many findings reference them, and an upload
paid for once is never paid for again. Making that the storage key means the property holds
in the store too: two findings sharing a photograph share the file, and re-uploading after a
crash overwrites a byte-identical file rather than growing the store.

Deleting is refcounted rather than cascaded. A key can be referenced by more than one row —
that is the whole point of hashing the content — so removing a finding must not remove bytes
another finding is still pointing at. The store deletes a blob only when the database says
nothing references it any more; see :func:`inspection_report.store.db.forget_orphan_blobs`.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from inspection_report.logging import get_logger

_log = get_logger("inspection_report.store.blobs")

# A blob key: the photograph's sha256, or that with `-t` for its thumbnail.
_KEY = re.compile(r"[0-9a-f]{16,64}(-t)?")

THUMBNAIL_SUFFIX = "-t"


def thumbnail_key(sha256: str) -> str:
    """The key a photograph's thumbnail is stored under. One place, so it cannot drift."""
    return f"{sha256}{THUMBNAIL_SUFFIX}"


class BlobError(RuntimeError):
    """A blob could not be stored or read. The message names the cause and the fix."""


@runtime_checkable
class BlobStore(Protocol):
    """Everything this build asks of a place to keep bytes."""

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes | None: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...


class FilesystemBlobStore:
    """Blobs on a mounted volume, fanned out two levels by key prefix.

    The fan-out is not decoration: tens of thousands of files in one directory is slow to
    list and unpleasant to operate on. ``ab/cd/abcdef…`` keeps any single directory small.

    Writes go to a temporary file in the same directory and are then renamed. Rename is
    atomic within a filesystem, so a reader never sees a partially written photograph and a
    crash mid-write leaves a stray temp file rather than a corrupt blob.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BlobError(
                f"cannot create the photo store at {self._root}: {exc}. Set PHOTO_STORE_DIR "
                f"to a writable path, or check the volume mount."
            ) from exc

    def _path(self, key: str) -> Path:
        # Keys are a content hash, optionally with the thumbnail suffix. Validating the shape
        # here is what stops a key ever being read as a path — no separator and no `..` can
        # match, so a key can never escape the root however it was constructed upstream.
        if not _KEY.fullmatch(key):
            raise BlobError(
                f"{key!r} is not a valid blob key; a key is a hex content hash, optionally "
                f"suffixed '-t' for a thumbnail."
            )
        return self._root / key[:2] / key[2:4] / key

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.replace(tmp, path)  # atomic within the filesystem
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise BlobError(f"could not write photograph {key[:12]}: {exc}") from exc

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise BlobError(f"could not read photograph {key[:12]}: {exc}") from exc

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        """Remove a blob. Missing is not an error — the caller wants it gone either way."""
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as exc:
            # A blob that will not delete is a housekeeping problem, not a reason to fail
            # the delete the user asked for: the row is already gone.
            _log.warning("blob_delete_failed", extra={"key": key[:12], "error": str(exc)[:80]})


def default_store() -> BlobStore:
    """The store this deployment uses. One place to swap the filesystem for a bucket."""
    return FilesystemBlobStore(os.environ.get("PHOTO_STORE_DIR", "data/photos"))
