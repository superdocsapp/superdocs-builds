"""
Resumable-progress tracking for `generate.build_response_packet`.

Before this module, a crash (process killed, gunicorn worker recycled,
network partition) partway through a multi-turn SuperDocs drafting run
left nothing behind: a retried call started over from item 1, re-running
`client.chat()` for every RFE item -- including ones that had already
been successfully drafted -- silently double-spending SuperDocs
operations on every retry of a large filing.

`ProgressStore` persists, after every single item, which request_ids
have already been drafted and what their outcome was (answered / not
answered, and the reply text if answered), keyed by `session_id`. A
retried `build_response_packet` call for the same `session_id` loads
this first and skips straight to the items that are still pending,
combined with SuperDocsClient's `idempotency_key` support (see
superdocs_client.py) so even an in-flight-but-uncertain single item
retry can't double-draft that item server-side either.

Stored as one JSON file per session under `PROGRESS_DIR` (default
`/tmp/rfe_progress`) -- deliberately not the shared review-session
database, since progress is scoped to a single drafting run's lifetime
and is cleaned up (`clear`) as soon as that run finishes, successfully
or not; this is a resumability aid, not a durable audit record (that's
`audit.py`).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

PROGRESS_DIR = os.environ.get("PROGRESS_DIR", "/tmp/rfe_progress")


@dataclass
class ItemProgress:
    request_id: str
    answered: bool
    reply_text: str = ""


class ProgressStore:
    def __init__(self, session_id: str, base_dir: str | None = None):
        self.session_id = session_id
        self.base_dir = Path(base_dir or PROGRESS_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.base_dir / f"{session_id}.json"

    def load(self) -> dict[str, ItemProgress]:
        """Returns {request_id: ItemProgress} for whatever's already been
        recorded for this session_id. Empty dict (not an error) if
        nothing has been recorded yet, or if the file is corrupt --
        resumability is a best-effort optimization, never something that
        should block a fresh drafting run from proceeding."""
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return {k: ItemProgress(**v) for k, v in raw.items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}

    def record(self, request_id: str, answered: bool, reply_text: str = "") -> None:
        """Persists one item's outcome immediately (not batched) so a
        crash right after this call still leaves the item marked done
        for the next resume attempt."""
        current = self.load()
        current[request_id] = ItemProgress(request_id=request_id, answered=answered, reply_text=reply_text)
        self._path.write_text(
            json.dumps({k: asdict(v) for k, v in current.items()}, indent=2), encoding="utf-8",
        )

    def clear(self) -> None:
        """Called once a drafting run finishes (successfully or not) so a
        genuinely NEW run for the same session_id doesn't accidentally
        inherit stale progress from an old attempt."""
        self._path.unlink(missing_ok=True)
