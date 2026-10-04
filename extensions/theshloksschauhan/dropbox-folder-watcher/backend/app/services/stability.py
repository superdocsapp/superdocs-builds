"""File stability detection for Dropbox sync.

This is the core of the card's named differentiator: "survives Dropbox's
sync behaviour without processing half-written files."

Strategy: content-hash + rev stability with debounce.

1. On any event for a path, record (path, content_hash, rev, observed_at).
2. Wait a configurable debounce window.
3. Re-fetch metadata. If content_hash AND rev are unchanged -> STABLE.
4. If changed, restart the debounce clock on the new observation.

Why this approach:
- content_hash is Dropbox's own integrity signal (not a side-channel like timestamps).
- rev gives us a clean idempotency key downstream.
- Two metadata calls, not two downloads — cheap.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.dropbox_event import DropboxEvent
from app.services.dropbox_client import DropboxClientProtocol, FileMetadata

logger = logging.getLogger(__name__)


class StabilityResult:
    """Result of a stability check."""

    def __init__(self, is_stable: bool, metadata: Optional[FileMetadata] = None,
                 reason: str = ""):
        self.is_stable = is_stable
        self.metadata = metadata
        self.reason = reason

    def __repr__(self) -> str:
        return f"StabilityResult(stable={self.is_stable}, reason='{self.reason}')"


def record_observation(
    db: Session,
    path: str,
    metadata: FileMetadata,
    resolved_job_id: Optional[UUID] = None,
) -> DropboxEvent:
    """Record a raw observation of a file's metadata. Append-only."""
    event = DropboxEvent(
        dropbox_path=path,
        content_hash=metadata.content_hash,
        rev=metadata.rev,
        size=metadata.size,
        client_modified=datetime.fromisoformat(metadata.client_modified) if metadata.client_modified else None,
        resolved_job_id=resolved_job_id,
    )
    db.add(event)
    db.flush()  # Get the ID without committing
    logger.debug("Recorded observation for %s: hash=%s rev=%s",
                 path, metadata.content_hash, metadata.rev)
    return event


def check_stability(
    db: Session,
    path: str,
    current_metadata: FileMetadata,
    debounce_seconds: int = 30,
) -> StabilityResult:
    """Determine whether a file is stable and safe to process.

    Checks whether the file's content_hash and rev have been unchanged
    for at least `debounce_seconds`. This is the authoritative stability
    signal — never process a file that hasn't passed this check.

    Args:
        db: Database session.
        path: Dropbox file path.
        current_metadata: The metadata just fetched from Dropbox.
        debounce_seconds: How many seconds the file must be unchanged.

    Returns:
        StabilityResult with is_stable=True if safe to process.
    """
    if not current_metadata.content_hash or not current_metadata.rev:
        return StabilityResult(
            is_stable=False,
            metadata=current_metadata,
            reason="Missing content_hash or rev — file may not be fully synced",
        )

    # Find the earliest prior observation for this path (used to measure stable elapsed time)
    prior = (
        db.query(DropboxEvent)
        .filter(
            DropboxEvent.dropbox_path == path,
            DropboxEvent.content_hash == current_metadata.content_hash,
            DropboxEvent.rev == current_metadata.rev,
        )
        .order_by(DropboxEvent.observed_at.asc())
        .first()
    )

    if prior is None:
        # First time seeing this hash/rev combination — record and wait
        record_observation(db, path, current_metadata)
        return StabilityResult(
            is_stable=False,
            metadata=current_metadata,
            reason=f"First observation of hash={current_metadata.content_hash[:12]}... — "
                   f"will recheck after {debounce_seconds}s",
        )

    # We've seen this exact hash+rev before. Has the debounce window elapsed?
    now = datetime.now(timezone.utc)
    # Handle naive datetimes from the database
    observed_at = prior.observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    elapsed = (now - observed_at).total_seconds()

    if elapsed < debounce_seconds:
        remaining = debounce_seconds - elapsed
        return StabilityResult(
            is_stable=False,
            metadata=current_metadata,
            reason=f"Hash stable but only {elapsed:.0f}s elapsed "
                   f"(need {debounce_seconds}s, {remaining:.0f}s remaining)",
        )

    # Hash and rev unchanged for the full debounce window -> STABLE
    logger.info(
        "File %s is STABLE: hash=%s rev=%s, stable for %.0fs",
        path, current_metadata.content_hash[:12], current_metadata.rev, elapsed,
    )
    return StabilityResult(
        is_stable=True,
        metadata=current_metadata,
        reason=f"Stable for {elapsed:.0f}s (threshold: {debounce_seconds}s)",
    )


def has_hash_changed_since_observation(
    db: Session,
    path: str,
    current_metadata: FileMetadata,
) -> bool:
    """Check if the content hash has changed since the last observation.

    Used to detect files that are still being uploaded (hash keeps changing).
    """
    latest = (
        db.query(DropboxEvent)
        .filter(DropboxEvent.dropbox_path == path)
        .order_by(DropboxEvent.observed_at.desc())
        .first()
    )

    if latest is None:
        return True  # No prior observation — treat as "changed"

    return latest.content_hash != current_metadata.content_hash
