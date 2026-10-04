"""Fake Dropbox client for testing.

Implements the same DropboxClientProtocol as the real client but returns
canned responses. Simulates real Dropbox behaviors like:
- Partially uploaded files (content_hash changes between calls)
- Files that disappear mid-processing
- Normal stable files
- Files being renamed

No real API calls are ever made. Tests run without a Dropbox access token.
"""
from typing import Optional
from dataclasses import dataclass, field

from app.services.dropbox_client import FileMetadata, ListFolderResult


class FakeDropboxClient:
    """Test double for the Dropbox client.

    Pre-load it with files and their metadata. Control what metadata
    is returned on successive calls to simulate sync behavior.
    """

    def __init__(self):
        # path -> list of FileMetadata (each call pops the next one)
        # If the list has one entry, the same metadata is returned every time.
        self._files: dict[str, list[FileMetadata]] = {}
        self._deleted_paths: set[str] = set()
        self._uploaded: list[tuple[str, bytes, bool]] = []  # Track uploads
        self._call_counts: dict[str, int] = {}  # Track API call counts

    def add_file(self, metadata: FileMetadata) -> None:
        """Add a file with fixed metadata (always returns the same thing)."""
        self._files[metadata.path] = [metadata]

    def add_file_sequence(self, path: str, sequence: list[FileMetadata]) -> None:
        """Add a file that returns different metadata on successive calls.

        Use this to simulate a file whose content_hash is still changing
        (upload in progress). The sequence is consumed in order; once
        exhausted, the last entry is returned forever.
        """
        self._files[path] = list(sequence)

    def delete_file(self, path: str) -> None:
        """Simulate a file being deleted from Dropbox."""
        self._deleted_paths.add(path)

    def list_folder(self, path: str) -> ListFolderResult:
        """List all files whose path starts with the given folder path."""
        self._call_counts["list_folder"] = self._call_counts.get("list_folder", 0) + 1
        entries = []
        for file_path, meta_list in self._files.items():
            if file_path.startswith(path) and file_path not in self._deleted_paths:
                meta = meta_list[0] if len(meta_list) == 1 else meta_list[0]
                entries.append(meta)
        return ListFolderResult(entries=entries, cursor="fake_cursor_1", has_more=False)

    def list_folder_continue(self, cursor: str) -> ListFolderResult:
        """No additional pages in the fake client."""
        self._call_counts["list_folder_continue"] = self._call_counts.get("list_folder_continue", 0) + 1
        return ListFolderResult(entries=[], cursor=cursor, has_more=False)

    def get_metadata(self, path: str) -> Optional[FileMetadata]:
        """Return the next metadata in the sequence for this path."""
        self._call_counts["get_metadata"] = self._call_counts.get("get_metadata", 0) + 1

        if path in self._deleted_paths:
            return None

        if path not in self._files:
            return None

        meta_list = self._files[path]
        if len(meta_list) == 0:
            return None
        elif len(meta_list) == 1:
            return meta_list[0]
        else:
            # Pop the first entry; successive calls get new metadata
            return meta_list.pop(0)

    def download_file(self, path: str, rev: Optional[str] = None) -> bytes:
        """Return fake file content."""
        self._call_counts["download_file"] = self._call_counts.get("download_file", 0) + 1
        if path in self._deleted_paths or path not in self._files:
            raise Exception(f"File not found: {path}")
        return b"fake file content for " + path.encode()

    def upload_file(self, path: str, content: bytes, overwrite: bool = False) -> FileMetadata:
        """Record an upload and return fake metadata for the uploaded file."""
        self._call_counts["upload_file"] = self._call_counts.get("upload_file", 0) + 1
        self._uploaded.append((path, content, overwrite))
        return FileMetadata(
            path=path,
            name=path.rsplit("/", 1)[-1],
            rev="uploaded_rev_001",
            content_hash="uploaded_hash_001",
            size=len(content),
        )

    @property
    def uploads(self) -> list[tuple[str, bytes, bool]]:
        """Inspect what was uploaded during the test."""
        return self._uploaded

    @property
    def call_counts(self) -> dict[str, int]:
        """Inspect how many times each API method was called."""
        return dict(self._call_counts)


# ---------- Pre-built test scenarios ----------

import hashlib

def make_stable_file(path: str = "/Clients/Acme/Inbox/report.docx") -> FileMetadata:
    """A file that is fully uploaded and stable. Unique per path."""
    path_hash = hashlib.md5(path.encode()).hexdigest()
    return FileMetadata(
        path=path,
        name=path.rsplit("/", 1)[-1],
        rev=f"stable_rev_{path_hash[:8]}",
        content_hash=f"{path_hash}{path_hash}",  # 64 chars
        size=45000,
        client_modified="2026-08-13T10:00:00",
    )


def make_unstable_file_sequence(path: str = "/Clients/Acme/Inbox/large.docx") -> list[FileMetadata]:
    """A file that is still being uploaded — hash changes between observations."""
    return [
        FileMetadata(
            path=path, name="large.docx",
            rev="partial_rev_1", content_hash="partial_hash_aaa", size=10000,
        ),
        FileMetadata(
            path=path, name="large.docx",
            rev="partial_rev_2", content_hash="partial_hash_bbb", size=25000,
        ),
        FileMetadata(
            path=path, name="large.docx",
            rev="final_rev_3", content_hash="final_hash_ccc", size=45000,
        ),
        # Last entry repeats (file is now stable)
        FileMetadata(
            path=path, name="large.docx",
            rev="final_rev_3", content_hash="final_hash_ccc", size=45000,
        ),
    ]


def make_output_file(path: str = "/Clients/Acme/Inbox/report.superdocs.normalized.docx") -> FileMetadata:
    """A file that is one of our own outputs (matches naming convention)."""
    return FileMetadata(
        path=path,
        name=path.rsplit("/", 1)[-1],
        rev="output_rev_xyz789",
        content_hash="output_hash_xyz789xyz789xyz789xyz789xyz789xyz789xyz789xyz789xyz789abcd",
        size=50000,
    )
