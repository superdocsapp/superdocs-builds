"""The blob store: where photograph bytes live now.

Keyless and databaseless — a filesystem store on a temp directory is the real thing, not a
stand-in, so these run in the ordinary suite.
"""

from __future__ import annotations

import hashlib

import pytest

from inspection_report.store.blobs import BlobError, BlobStore, FilesystemBlobStore, thumbnail_key


@pytest.fixture
def store(tmp_path) -> FilesystemBlobStore:  # type: ignore[no-untyped-def]
    return FilesystemBlobStore(tmp_path / "photos")


def _key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestItKeepsBytes:
    def test_it_satisfies_the_protocol(self, store: FilesystemBlobStore) -> None:
        assert isinstance(store, BlobStore)

    def test_what_goes_in_comes_out(self, store: FilesystemBlobStore) -> None:
        data = b"\x89PNG\r\n\x1a\n" + b"pixels" * 100
        store.put(_key(data), data)
        assert store.get(_key(data)) == data

    def test_a_missing_key_is_none_not_an_error(self, store: FilesystemBlobStore) -> None:
        """A row pointing at nothing is a condition the caller handles, not a crash."""
        assert store.get(_key(b"never stored")) is None
        assert store.exists(_key(b"never stored")) is False

    def test_writing_the_same_content_twice_is_one_blob(self, store: FilesystemBlobStore) -> None:
        """Keys are content hashes, so a retry after a crash does not grow the store."""
        data = b"same bytes"
        store.put(_key(data), data)
        store.put(_key(data), data)
        files = [p for p in (store._root).rglob("*") if p.is_file()]
        assert len(files) == 1

    def test_a_thumbnail_sits_beside_its_photograph(self, store: FilesystemBlobStore) -> None:
        data = b"full size"
        store.put(_key(data), data)
        store.put(thumbnail_key(_key(data)), b"small")
        assert store.get(_key(data)) == b"full size"
        assert store.get(thumbnail_key(_key(data))) == b"small"


class TestAKeyCannotEscapeTheStore:
    """The key reaches the filesystem, so its shape is a security boundary."""

    @pytest.mark.parametrize(
        "key",
        [
            "../../../../etc/passwd",
            "..",
            "a/b",
            "abc",  # too short to be a hash
            "ZZZZZZZZZZZZZZZZ",  # not hex
            "",
            "0123456789abcdef/../../x",
        ],
    )
    def test_a_key_that_is_not_a_hash_is_refused(
        self, store: FilesystemBlobStore, key: str
    ) -> None:
        with pytest.raises(BlobError):
            store.put(key, b"payload")
        with pytest.raises(BlobError):
            store.get(key)

    def test_nothing_was_written_outside_the_root(self, store: FilesystemBlobStore) -> None:
        with pytest.raises(BlobError):
            store.put("../escaped", b"payload")
        assert not (store._root.parent / "escaped").exists()
