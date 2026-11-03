"""Tamper-evident audit trail via hash chaining.

The audit trail (MetadataHistoryStore / SqliteHistoryStore) is the one
artifact a regulator or auditor actually leans on: "prove nothing was
altered after the fact." A plain SQLite table doesn't prove that --
anyone with write access to the .db file can UPDATE a row and there is
nothing to notice. Real WORM storage (S3 Object Lock, an append-only
ledger service) is the correct answer at real deployment scale and is
explicitly out of scope for this sandbox (see README's infra-needed
list). What IS buildable and testable here: make tampering
*detectable*, even if not physically *prevented* -- which is most of
the actual value; an auditor doesn't need the tampering to be
impossible, they need a mechanism that reliably tells them whether it
happened.

Design: each file has its own hash chain (audit trails are queried and
reasoned about per-file, so a global chain would mix unrelated files'
integrity together for no benefit). Every MetadataChange entry's
entry_hash = sha256(prev_hash + a canonical serialization of every
other field on the entry). prev_hash is the previous entry's
entry_hash, or GENESIS_HASH for a file's first entry. Recomputing
entry_hash from an entry's stored fields and comparing it to what's
stored -- for every entry in order -- proves whether anything was
altered: change any field of any entry (including years later) and
every entry_hash from that point forward stops matching its recomputed
value.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.models import MetadataChange

GENESIS_HASH = "0" * 64


def _canonical_payload(
    file_id: str,
    field_name: str,
    old_value: Optional[str],
    new_value: Optional[str],
    version_sha1: str,
    timestamp: float,
    reason: str,
    source_session_id: Optional[str],
    prev_hash: str,
) -> bytes:
    """Fixed field order and an explicit sentinel for None (rather than
    Python's str(None) == "None", which would collide with a literal
    string value "None") -- deterministic byte-for-byte regardless of
    dict ordering or serialization library defaults."""
    parts = [
        prev_hash,
        file_id,
        field_name,
        "\x00" if old_value is None else old_value,
        "\x00" if new_value is None else new_value,
        version_sha1,
        repr(timestamp),
        reason,
        "\x00" if source_session_id is None else source_session_id,
    ]
    return "\x1f".join(parts).encode("utf-8")


def compute_entry_hash(
    prev_hash: str,
    file_id: str,
    field_name: str,
    old_value: Optional[str],
    new_value: Optional[str],
    version_sha1: str,
    timestamp: float,
    reason: str,
    source_session_id: Optional[str],
) -> str:
    payload = _canonical_payload(
        file_id, field_name, old_value, new_value, version_sha1, timestamp, reason, source_session_id, prev_hash
    )
    return hashlib.sha256(payload).hexdigest()


@dataclass
class ChainVerificationResult:
    valid: bool
    checked_count: int
    unverifiable_prefix_count: int  # pre-migration entries with no hash at all
    first_break_index: Optional[int] = None  # index into the checked (post-prefix) entries
    detail: str = ""


def verify_chain(entries: list["MetadataChange"]) -> ChainVerificationResult:
    """Entries must be in the original insertion order for this file
    (get_history() already returns them that way -- ordered by
    autoincrement id / insertion order). Recomputes every entry's hash
    from its stored fields and checks it against both the stored
    entry_hash and the expected prev_hash link to the entry before it.

    Entries with entry_hash is None are treated as an unverifiable
    prefix (pre-migration data) rather than a break -- they simply
    can't be checked, which is reported honestly via
    unverifiable_prefix_count rather than silently passed or failed."""
    unverifiable_prefix = 0
    i = 0
    while i < len(entries) and entries[i].entry_hash is None:
        unverifiable_prefix += 1
        i += 1

    # Whether this file has any legacy (unverifiable) entries or not,
    # the checked segment always starts its chain at GENESIS_HASH: a
    # legacy entry has no entry_hash to link from, so treating it as
    # "chain start" (same as a brand-new file) is the only sound
    # option -- it can't be cryptographically tied to what came before
    # it, by definition.
    expected_prev = GENESIS_HASH
    checked = entries[i:]
    for idx, entry in enumerate(checked):
        if entry.prev_hash != expected_prev:
            return ChainVerificationResult(
                valid=False,
                checked_count=idx,
                unverifiable_prefix_count=unverifiable_prefix,
                first_break_index=idx,
                detail=f"entry {idx} (field={entry.field_name}) prev_hash link does not match the "
                f"preceding entry's hash -- an entry may have been deleted, reordered, or inserted",
            )
        recomputed = compute_entry_hash(
            entry.prev_hash,
            entry.file_id,
            entry.field_name,
            entry.old_value,
            entry.new_value,
            entry.version_sha1,
            entry.timestamp,
            entry.reason,
            entry.source_session_id,
        )
        if recomputed != entry.entry_hash:
            return ChainVerificationResult(
                valid=False,
                checked_count=idx,
                unverifiable_prefix_count=unverifiable_prefix,
                first_break_index=idx,
                detail=f"entry {idx} (field={entry.field_name}) hash does not match its stored fields "
                f"-- this entry was altered after being written",
            )
        expected_prev = entry.entry_hash

    return ChainVerificationResult(
        valid=True,
        checked_count=len(checked),
        unverifiable_prefix_count=unverifiable_prefix,
        detail="chain intact" if not unverifiable_prefix else f"chain intact ({unverifiable_prefix} pre-migration entries unverifiable)",
    )
