"""Per-file metadata change history: what changed, when, and because of
which source version.

Only ever appended to when a field's value actually changes -- comparing
against the last known value before writing an entry -- which is what
makes "the parts the new source did not affect stay exactly as they
were, and the system can prove that" a checkable fact instead of a claim.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from app.models import MetadataChange
from app.workflow.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain


class MetadataHistoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: dict[str, list[MetadataChange]] = {}
        self._last_values: dict[str, dict[str, Any]] = {}

    def record_diff(
        self,
        file_id: str,
        version_sha1: str,
        new_fields: dict[str, Any],
        reason: str,
        session_ids: Optional[dict[str, str]] = None,
    ) -> list[MetadataChange]:
        """Compares new_fields against the last committed values for this
        file and records a MetadataChange entry only for keys that
        actually changed value (including a key disappearing, which we
        treat as changing to None). Returns the entries it wrote.

        session_ids (optional), keyed the same way as new_fields, lets
        the caller attach the SuperDocs chat session that produced each
        field's value -- provenance for "prove where this came from,"
        not just "when did it change." A key with no entry in
        session_ids (e.g. a value that came from human review approval,
        not a live SuperDocs call) simply gets None, which is itself an
        honest answer, not a missing one.

        Every entry written here is hash-chained to the previous entry
        for this file (see app/workflow/hash_chain.py) -- entry_hash
        covers every other field on the entry plus the previous entry's
        hash, so altering any stored field of any past entry, or
        deleting/reordering entries, becomes detectable via
        verify_history() below rather than silently possible."""
        with self._lock:
            previous = self._last_values.get(file_id, {})
            all_keys = set(previous) | set(new_fields)
            entries: list[MetadataChange] = []
            now = time.time()
            chain = self._history.get(file_id, [])
            prev_hash = chain[-1].entry_hash if chain and chain[-1].entry_hash else GENESIS_HASH
            for key in sorted(all_keys):
                old_val = previous.get(key)
                new_val = new_fields.get(key)
                if old_val == new_val:
                    continue
                old_str = None if old_val is None else str(old_val)
                new_str = None if new_val is None else str(new_val)
                source_session_id = (session_ids or {}).get(key)
                entry_hash = compute_entry_hash(
                    prev_hash, file_id, key, old_str, new_str, version_sha1, now, reason, source_session_id
                )
                entry = MetadataChange(
                    file_id=file_id,
                    field_name=key,
                    old_value=old_str,
                    new_value=new_str,
                    version_sha1=version_sha1,
                    timestamp=now,
                    reason=reason,
                    source_session_id=source_session_id,
                    prev_hash=prev_hash,
                    entry_hash=entry_hash,
                )
                entries.append(entry)
                self._history.setdefault(file_id, []).append(entry)
                prev_hash = entry_hash
            self._last_values[file_id] = dict(new_fields)
            return entries

    def get_history(self, file_id: str) -> list[MetadataChange]:
        with self._lock:
            return list(self._history.get(file_id, []))

    def verify_history(self, file_id: str):
        """Convenience wrapper: recomputes and checks this file's whole
        chain in one call. Returns a hash_chain.ChainVerificationResult."""
        return verify_chain(self.get_history(file_id))
