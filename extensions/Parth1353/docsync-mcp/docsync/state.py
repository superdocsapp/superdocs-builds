"""What this tool remembers between runs, in ``.docsync/``.

Two files, both plain JSON, both safe to commit.

``state.json`` holds the SuperDocs session and document ids, the content hash
of each document as SuperDocs last saw it, and the fact snapshot taken after
the last successful apply. The snapshot is what makes ``docsync plan`` useful
without git: it answers "what has moved since the docs were last brought into
step", which is a different and often better question than "what does this
branch change".

``pending.json`` holds a staged batch — edits that have been sent, have paused
at the human gate, and have not been decided yet. It exists because the gate in
an editor is not a blocking prompt: the agent calls ``docsync_apply``, a person
looks at the diffs in their own time, and ``docsync_approve`` arrives in a
different process minutes later. Without this file that pause would have
nowhere to live.

Committing ``.docsync/state.json`` is the right default — the document ids are
shared team state, and a colleague who does not have them re-uploads every
document and pays for it.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STATE_DIR = ".docsync"


class StateError(RuntimeError):
    pass


@dataclass
class DocumentRecord:
    document_id: str
    content_hash: str
    uploaded_at: str = ""
    title: str = ""
    session_id: str = ""
    #: Hash of what docsync itself last wrote to this file, which is NOT the
    #: same as `content_hash` (what it last uploaded). The upload hash is taken
    #: from the file as found, so it already includes anything a person edited
    #: in the meantime — using it to decide "did we write this" would let the
    #: tool overwrite exactly the work it is meant to protect.
    written_hash: str = ""


@dataclass
class State:
    root: Path
    session_id: str = ""
    documents: dict[str, DocumentRecord] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""
    #: Distinguishes this checkout from any other holding the same registry.
    #: Generated once; recorded so a colleague with this file reuses the
    #: same SuperDocs sessions instead of re-uploading every document.
    workspace_id: str = ""

    @property
    def path(self) -> Path:
        return self.root / STATE_DIR / "state.json"

    @classmethod
    def load(cls, root: Path, *, session_id: str = "") -> State:
        path = root / STATE_DIR / "state.json"
        if not path.exists():
            return cls(root=root, session_id=session_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(
                f"{path} is not readable JSON: {exc}\n"
                f"  → delete it to start again; the next apply will re-upload every document"
            ) from exc
        docs = {
            key: DocumentRecord(**value)
            for key, value in (raw.get("documents") or {}).items()
            if isinstance(value, dict) and "document_id" in value
        }
        return cls(
            root=root,
            session_id=raw.get("session_id") or session_id,
            documents=docs,
            facts=raw.get("facts") or {},
            updated_at=raw.get("updated_at", ""),
            workspace_id=raw.get("workspace_id", ""),
        )

    def save(self) -> None:
        self.workspace_id = self.workspace_id or secrets.token_hex(4)
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
            "updated_at": self.updated_at,
            "documents": {key: asdict(value) for key, value in sorted(self.documents.items())},
            "facts": self.facts,
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def uploaded(self) -> dict[str, str]:
        """path → content hash SuperDocs already holds."""
        return {key: record.content_hash for key, record in self.documents.items()}

    def record_upload(
        self,
        path: str,
        document_id: str,
        content_hash: str,
        title: str,
        session_id: str = "",
    ) -> None:
        previous = self.documents.get(path)
        self.documents[path] = DocumentRecord(
            document_id=document_id,
            content_hash=content_hash,
            uploaded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            title=title,
            session_id=session_id,
            written_hash=previous.written_hash if previous else "",
        )

    def mark_written(self, path: str, written_hash: str) -> None:
        """Record what docsync just wrote to disk, so a later round can tell
        its own output from somebody else's uncommitted work."""
        record = self.documents.get(path)
        if record is not None:
            record.written_hash = written_hash
            record.content_hash = written_hash


# ---------------------------------------------------------------------------


@dataclass
class PendingChange:
    change_id: str
    operation: str
    old_text: str
    new_text: str
    explanation: str = ""


@dataclass
class PendingJob:
    path: str
    title: str
    document_id: str
    job_id: str
    instruction: str
    front_matter: str
    session_id: str = ""
    changes: list[PendingChange] = field(default_factory=list)
    verifiable: list[dict[str, str]] = field(default_factory=list)
    unverifiable: list[dict[str, str]] = field(default_factory=list)
    invariants: list[dict[str, str]] = field(default_factory=list)
    error: str = ""


@dataclass
class Pending:
    root: Path
    session_id: str = ""
    created_at: str = ""
    jobs: list[PendingJob] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return self.root / STATE_DIR / "pending.json"

    @property
    def change_count(self) -> int:
        return sum(len(job.changes) for job in self.jobs)

    @classmethod
    def load(cls, root: Path) -> Pending | None:
        path = root / STATE_DIR / "pending.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f"{path} is not readable JSON: {exc}") from exc
        jobs = []
        for item in raw.get("jobs") or []:
            changes = [PendingChange(**c) for c in item.pop("changes", [])]
            jobs.append(PendingJob(changes=changes, **item))
        return cls(
            root=root,
            session_id=raw.get("session_id", ""),
            created_at=raw.get("created_at", ""),
            jobs=jobs,
        )

    def save(self) -> None:
        self.created_at = self.created_at or time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "jobs": [
                {**asdict(job), "changes": [asdict(c) for c in job.changes]} for job in self.jobs
            ],
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def find(self, change_id: str) -> tuple[PendingJob, PendingChange] | None:
        for job in self.jobs:
            for change in job.changes:
                if change.change_id == change_id:
                    return job, change
        return None
