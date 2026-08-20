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


class MetadataHistoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: dict[str, list[MetadataChange]] = {}
        self._last_values: dict[str, dict[str, Any]] = {}

    def record_diff(
        self, file_id: str, version_sha1: str, new_fields: dict[str, Any], reason: str
    ) -> list[MetadataChange]:
        """Compares new_fields against the last committed values for this
        file and records a MetadataChange entry only for keys that
        actually changed value (including a key disappearing, which we
        treat as changing to None). Returns the entries it wrote."""
        with self._lock:
            previous = self._last_values.get(file_id, {})
            all_keys = set(previous) | set(new_fields)
            entries: list[MetadataChange] = []
            now = time.time()
            for key in sorted(all_keys):
                old_val = previous.get(key)
                new_val = new_fields.get(key)
                if old_val == new_val:
                    continue
                entry = MetadataChange(
                    file_id=file_id,
                    field_name=key,
                    old_value=None if old_val is None else str(old_val),
                    new_value=None if new_val is None else str(new_val),
                    version_sha1=version_sha1,
                    timestamp=now,
                    reason=reason,
                )
                entries.append(entry)
                self._history.setdefault(file_id, []).append(entry)
            self._last_values[file_id] = dict(new_fields)
            return entries

    def get_history(self, file_id: str) -> list[MetadataChange]:
        with self._lock:
            return list(self._history.get(file_id, []))
