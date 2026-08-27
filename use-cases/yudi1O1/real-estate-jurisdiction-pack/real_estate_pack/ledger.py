"""Idempotency for an operation that costs money.

CARRIED OVER from the sibling `supplier-quality-drafter` build in this folder,
with one change that matters for this project: a pack is THREE documents, so the
fingerprint is taken per document rather than per run. Re-running a pack after
answering one more disclosure question re-bills only the documents whose content
actually changed — the compliance index changes, the lease often does not.

Drafting a document is a billable SuperDocs operation. Running the same draft
twice by accident — a re-run after a crash, a CI job that fires twice, someone
pressing up-arrow-enter — should not spend a second operation to produce a byte
for byte identical result.

So every draft is fingerprinted over everything that could change its output:
the session, the exact instruction (which already encodes every engineer-supplied
number), the template's bytes, and the export format. If that fingerprint has
completed before AND its output file is still on disk, the draft is skipped and
the previous result stands.

Two deliberate refusals to be clever:

* **A recorded run whose output file has since been deleted is NOT treated as
  done.** The ledger records what happened, but the file on disk is the source
  of truth about what still exists. Claiming "already done" while pointing at a
  missing file would be exactly the kind of success message that isn't true.
* **The template is hashed by content, not by path.** Editing a template in
  place, keeping its name, correctly produces a new fingerprint.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_LEDGER_PATH = ".superdocs_ledger.json"


@dataclass
class LedgerEntry:
    fingerprint: str
    session_id: str
    export_path: str
    job_id: str
    completed_at: str


def fingerprint(session_id: str, instruction: str, template_path: str, export_format: str) -> str:
    h = hashlib.sha256()
    h.update(session_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(instruction.encode("utf-8"))
    h.update(b"\x00")
    h.update(export_format.encode("utf-8"))
    h.update(b"\x00")
    with open(template_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


class RunLedger:
    def __init__(self, path: str = DEFAULT_LEDGER_PATH):
        self.path = Path(path)

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            # A corrupt ledger must never block real work — the cost of ignoring
            # it is at worst one redundant operation, which is strictly better
            # than refusing to draft at all.
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so an interrupted save can't leave a half-written
        # ledger behind (the same reason the drafter itself is resumable-safe).
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent or "."), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def lookup(self, fp: str) -> Optional[LedgerEntry]:
        """Return a completed entry only if its output file still exists."""
        raw = self._load().get(fp)
        if not raw:
            return None
        entry = LedgerEntry(**raw)
        if not os.path.exists(entry.export_path):
            return None
        return entry

    def record(self, fp: str, session_id: str, export_path: str, job_id: str) -> LedgerEntry:
        entry = LedgerEntry(
            fingerprint=fp,
            session_id=session_id,
            export_path=os.path.abspath(export_path),
            job_id=job_id,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        data = self._load()
        data[fp] = asdict(entry)
        self._save(data)
        return entry
