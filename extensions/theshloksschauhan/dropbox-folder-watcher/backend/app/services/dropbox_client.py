"""Dropbox integration client.

Wraps the Dropbox SDK behind an abstraction so tests can use a fake
without hitting the real API. Every method that touches Dropbox goes
through this module — no direct SDK calls elsewhere in the codebase.
"""
import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import dropbox
from dropbox.files import FileMetadata as DbxFileMetadata, FolderMetadata, WriteMode

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------- Data types (decoupled from Dropbox SDK) ----------

@dataclass(frozen=True)
class FileMetadata:
    """Our own representation of a Dropbox file's metadata.
    Decoupled from the SDK so the rest of the app never imports dropbox.files."""
    path: str
    name: str
    rev: str
    content_hash: str
    size: int
    client_modified: Optional[str] = None  # ISO-8601 string
    server_modified: Optional[str] = None


@dataclass(frozen=True)
class ListFolderResult:
    """Result of listing a folder."""
    entries: list[FileMetadata]
    cursor: str
    has_more: bool


# ---------- Protocol (for dependency injection / testing) ----------

class DropboxClientProtocol(Protocol):
    """Interface that both the real and fake clients implement."""

    def list_folder(self, path: str) -> ListFolderResult: ...

    def list_folder_continue(self, cursor: str) -> ListFolderResult: ...

    def get_metadata(self, path: str) -> Optional[FileMetadata]: ...

    def download_file(self, path: str, rev: Optional[str] = None) -> bytes: ...

    def upload_file(self, path: str, content: bytes, overwrite: bool = False) -> FileMetadata: ...


# ---------- Real implementation ----------

def _convert_metadata(entry: DbxFileMetadata) -> FileMetadata:
    """Convert a Dropbox SDK FileMetadata to our own dataclass."""
    return FileMetadata(
        path=entry.path_display,
        name=entry.name,
        rev=entry.rev,
        content_hash=entry.content_hash,
        size=entry.size,
        client_modified=entry.client_modified.isoformat() if entry.client_modified else None,
        server_modified=entry.server_modified.isoformat() if entry.server_modified else None,
    )


class DropboxClient:
    """Real Dropbox client wrapping the official SDK."""

    def __init__(self, access_token: Optional[str] = None):
        token = access_token or settings.dropbox_access_token
        if not token:
            raise ValueError(
                "Dropbox access token not configured. "
                "Set DROPBOX_ACCESS_TOKEN in your .env file."
            )
        self._dbx = dropbox.Dropbox(token)
        logger.info("Dropbox client initialized")

    def list_folder(self, path: str) -> ListFolderResult:
        """List all files in a folder (first page)."""
        result = self._dbx.files_list_folder(path)
        entries = [
            _convert_metadata(e)
            for e in result.entries
            if isinstance(e, DbxFileMetadata)
        ]
        return ListFolderResult(
            entries=entries,
            cursor=result.cursor,
            has_more=result.has_more,
        )

    def list_folder_continue(self, cursor: str) -> ListFolderResult:
        """Continue listing from a previous cursor."""
        result = self._dbx.files_list_folder_continue(cursor)
        entries = [
            _convert_metadata(e)
            for e in result.entries
            if isinstance(e, DbxFileMetadata)
        ]
        return ListFolderResult(
            entries=entries,
            cursor=result.cursor,
            has_more=result.has_more,
        )

    def get_metadata(self, path: str) -> Optional[FileMetadata]:
        """Fetch metadata for a single file. Returns None if not found."""
        try:
            entry = self._dbx.files_get_metadata(path)
            if isinstance(entry, DbxFileMetadata):
                return _convert_metadata(entry)
            return None  # It's a folder, not a file
        except dropbox.exceptions.ApiError as e:
            if hasattr(e.error, 'is_path') and e.error.is_path():
                logger.warning("File not found at %s", path)
                return None
            raise

    def download_file(self, path: str, rev: Optional[str] = None) -> bytes:
        """Download file content. Optionally pin to a specific revision."""
        _, response = self._dbx.files_download(path, rev=rev)
        return response.content

    def upload_file(self, path: str, content: bytes, overwrite: bool = False) -> FileMetadata:
        """Upload a file to Dropbox. Returns metadata of the uploaded file."""
        mode = WriteMode.overwrite if overwrite else WriteMode.add
        entry = self._dbx.files_upload(content, path, mode=mode)
        return _convert_metadata(entry)


# ---------- Webhook verification ----------

def verify_webhook_signature(signature: str, body: bytes, secret: Optional[str] = None) -> bool:
    """Verify the X-Dropbox-Signature HMAC-SHA256 header.

    Returns True if the signature is valid, False otherwise.
    Never trust a webhook callback without this check.
    """
    app_secret = secret or settings.dropbox_app_secret
    if not app_secret:
        logger.error("Cannot verify webhook: DROPBOX_APP_SECRET not configured")
        return False

    expected = hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
