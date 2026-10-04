"""Anti-loop protection: prevents the system from reprocessing its own output.

The card's stopping rule is load-bearing: "the loop needs an explicit stopping
condition and a no-spend preview mode; it must never re-trigger on its own output."

Three layers of defense (belt-and-suspenders):
1. Naming convention: outputs use ".superdocs." in the filename.
2. Database lookup: known_outputs table checked by path on every event.
3. Content-hash check: catch copies of outputs even under different paths.

Layer 1 is a fast filter. Layers 2+3 are the authoritative checks.
"""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.known_output import KnownOutput

logger = logging.getLogger(__name__)

# The naming pattern marker — all outputs contain this substring
OUTPUT_MARKER = ".superdocs."


def is_output_by_naming(path: str) -> bool:
    """Fast first-pass check: does the filename match our output naming pattern?

    This is a soft guard — it catches the common case but we never trust it alone.
    A client could name their source file with '.superdocs.' in it, or rename
    our output. The DB-backed checks below are authoritative.
    """
    # Extract just the filename from the path
    filename = path.rsplit("/", 1)[-1] if "/" in path else path
    return OUTPUT_MARKER in filename.lower()


def is_known_output_by_path(db: Session, path: str) -> bool:
    """Check if this exact path exists in the known_outputs table.

    This is the primary authoritative check — if we produced a file at this
    path, it's recorded here with the job that created it.
    """
    exists = (
        db.query(KnownOutput.id)
        .filter(KnownOutput.output_path == path)
        .first()
    ) is not None

    if exists:
        logger.debug("Anti-loop: path %s is a known output — skipping", path)
    return exists


def is_known_output_by_hash(db: Session, content_hash: str) -> bool:
    """Check if this content hash matches any known output.

    Belt-and-suspenders: catches copies of our output under different paths
    (e.g., a client copies our output into a different watched folder).
    """
    if not content_hash:
        return False

    exists = (
        db.query(KnownOutput.id)
        .filter(KnownOutput.output_content_hash == content_hash)
        .first()
    ) is not None

    if exists:
        logger.debug("Anti-loop: hash %s matches a known output — skipping", content_hash[:12])
    return exists


def is_own_output(db: Session, path: str, content_hash: Optional[str] = None) -> bool:
    """The combined anti-loop check. Call this on every detected event.

    Returns True if this file should be skipped (it's our own output).
    Uses all three layers:
    1. Naming convention (fast path)
    2. Path lookup in known_outputs
    3. Content hash lookup in known_outputs

    Even if naming says "not an output", we still check the DB.
    Even if naming says "is an output", we log it but trust the DB as authoritative.
    """
    # Layer 1: Fast naming check
    naming_match = is_output_by_naming(path)

    # Layer 2: Path-based DB check
    path_match = is_known_output_by_path(db, path)

    # Layer 3: Hash-based DB check
    hash_match = is_known_output_by_hash(db, content_hash) if content_hash else False

    if path_match or hash_match:
        logger.info(
            "Anti-loop BLOCKED: path=%s (naming=%s, path_db=%s, hash_db=%s)",
            path, naming_match, path_match, hash_match,
        )
        return True

    if naming_match and not path_match and not hash_match:
        # Naming pattern matched but DB says it's not ours — this is suspicious
        # but we should still process it. Could be a client file that happens
        # to contain ".superdocs." in the name. Log it for audit.
        logger.warning(
            "Anti-loop WARNING: %s matches output naming pattern but is NOT "
            "in known_outputs. Processing anyway — may be a client file.",
            path,
        )

    return False


def register_output(
    db: Session,
    job_id: UUID,
    output_path: str,
    output_rev: Optional[str] = None,
    output_content_hash: Optional[str] = None,
) -> KnownOutput:
    """Register a file as a known output. Call this BEFORE/during the
    Dropbox upload returns, inside the same transaction boundary as
    marking the run COMPLETED.

    This is what makes the anti-loop check work after a restart —
    known_outputs is persisted in Postgres, not in-memory.
    """
    known = KnownOutput(
        job_id=job_id,
        output_path=output_path,
        output_rev=output_rev,
        output_content_hash=output_content_hash,
    )
    db.add(known)
    db.flush()
    logger.info(
        "Registered output: job=%s path=%s rev=%s hash=%s",
        job_id, output_path, output_rev,
        output_content_hash[:12] if output_content_hash else None,
    )
    return known
