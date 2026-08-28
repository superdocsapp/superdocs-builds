"""Ingest node — loads document bytes and validates MIME type.

This is the entry point of the Understand Stage. It reads document bytes
from the storage reference in `document_versions`, validates the MIME type
against the allowed set, and populates `raw_content` and `mime_type` in State.
"""

from __future__ import annotations

import uuid
from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.documents import DocumentVersion
from src.pipeline.state import PipelineState


# Allowed MIME types for document ingestion
ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    }
)


class StorageReader(Protocol):
    """Protocol for reading document bytes from storage.

    Implementations may read from local filesystem, S3, GCS, etc.
    """

    def read(self, storage_ref: str) -> Optional[bytes]:
        """Read document bytes from the given storage reference.

        Args:
            storage_ref: The storage path/URI for the document.

        Returns:
            The raw document bytes, or None if the file cannot be read.
        """
        ...


class DBStorageReader:
    """Default storage reader that looks up the storage_ref via SQLAlchemy
    and reads bytes from the referenced location.

    For this implementation, storage_ref is treated as a filesystem path.
    In production, this could be replaced with S3/GCS readers.
    """

    def __init__(self, session: Session):
        self._session = session

    def read(self, storage_ref: str) -> Optional[bytes]:
        """Read document bytes from a filesystem path."""
        try:
            with open(storage_ref, "rb") as f:
                return f.read()
        except (OSError, IOError):
            return None


async def ingest(
    state: PipelineState,
    *,
    db_session: Optional[Session] = None,
    storage_reader: Optional[StorageReader] = None,
) -> PipelineState:
    """Load document bytes from storage and validate MIME type.

    Reads the document version's storage_ref from the database, fetches
    the raw bytes, validates the MIME type, and populates State.

    Args:
        state: The current pipeline state containing document_id,
            document_version_id, and config.
        db_session: Optional SQLAlchemy session for database access.
            Required if storage_reader is not provided.
        storage_reader: Optional storage reader implementation.
            If not provided, uses DBStorageReader with db_session.

    Returns:
        Updated PipelineState with raw_content, mime_type, current_node,
        node_status, and completed_nodes set appropriately.
    """
    document_version_id = state["document_version_id"]

    # Look up the document version to get storage_ref and mime_type
    if db_session is None and storage_reader is None:
        return _error_state(
            state,
            error_detail="No database session or storage reader provided",
        )

    # Resolve storage_ref and mime_type from the database
    storage_ref: Optional[str] = None
    mime_type: Optional[str] = None

    if db_session is not None:
        version_row = db_session.execute(
            select(DocumentVersion).where(
                DocumentVersion.id == uuid.UUID(document_version_id)
            )
        ).scalar_one_or_none()

        if version_row is None:
            return _error_state(
                state,
                error_detail=f"Document version not found: {document_version_id}",
            )

        storage_ref = version_row.storage_ref
        # Get MIME type from the parent document
        mime_type = version_row.document.mime_type

    # Validate MIME type
    if mime_type is None or mime_type not in ALLOWED_MIME_TYPES:
        return _error_state(
            state,
            error_detail=(
                f"Invalid MIME type: {mime_type}. "
                f"Allowed: {sorted(ALLOWED_MIME_TYPES)}"
            ),
        )

    # Read document bytes
    if storage_reader is not None:
        raw_content = storage_reader.read(storage_ref or "")
    else:
        reader = DBStorageReader(db_session)  # type: ignore[arg-type]
        raw_content = reader.read(storage_ref or "")

    if raw_content is None:
        return _error_state(
            state,
            error_detail=f"Unable to read document from storage: {storage_ref}",
        )

    if len(raw_content) == 0:
        return _error_state(
            state,
            error_detail=f"Document has zero bytes: {storage_ref}",
        )

    # Success — populate state
    completed_nodes = list(state.get("completed_nodes", []))
    completed_nodes.append("ingest")

    return PipelineState(
        **{
            **state,
            "raw_content": raw_content,
            "mime_type": mime_type,
            "current_node": "ingest",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed_nodes,
        }
    )


def _error_state(state: PipelineState, *, error_detail: str) -> PipelineState:
    """Return an error state for the ingest node.

    All ingest errors are permanent — there is no retry support.
    """
    return PipelineState(
        **{
            **state,
            "current_node": "ingest",
            "node_status": "error",
            "error_type": "permanent",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )
