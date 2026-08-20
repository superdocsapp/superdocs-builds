"""In-memory Box client used by tests and local demo runs.

Behaves like the real API closely enough to exercise the workflow:
per-file version bumping, per-template metadata storage that only accepts
partial patches, and governance state that update_metadata refuses to
touch.

IMPORTANT: this client's file/metadata/governance state lives only in
this process's memory and does NOT survive a restart -- unlike the
pipeline's own SQLite-backed stores (review queue, audit history,
checkpoints, idempotency; see app/storage/sqlite_backend.py and
PERSISTENCE_DB_PATH), which do. Restarting a server running against this
client will show an empty file list even though a previously-persisted
review queue or audit trail entry might still reference a file_id this
client no longer knows about -- that's expected here, not a bug, and it
is specifically a property of testing/demoing against the fake. Against
RealBoxClient in a real deployment this gap does not exist, because Box
itself is the durable store for file and metadata state; only the data
this system owns (reviews, audit trail, checkpoints) needs its own
persistence, and that's what PERSISTENCE_DB_PATH is for.
"""
from __future__ import annotations

import hashlib
from typing import Any

from app.clients.box_client import BoxAPIError, BoxClient
from app.models import BoxFileVersion, GovernanceState

# Keys the workflow must never write, no matter what the caller passes.
_PROTECTED_KEYS = {"legal_hold", "retention_policy_locked", "classification_label"}


class FakeBoxClient(BoxClient):
    def __init__(self) -> None:
        self._files: dict[str, dict[str, Any]] = {}
        self._metadata: dict[tuple[str, str], dict[str, Any]] = {}
        self._governance: dict[str, GovernanceState] = {}
        self._next_synthetic_id = 9000

    # -- test/demo setup helpers -------------------------------------------------
    def seed_file(
        self,
        file_id: str,
        name: str,
        content: bytes,
        version_id: str = "1",
        governance: GovernanceState | None = None,
    ) -> None:
        self._files[file_id] = {"name": name, "content": content, "version_id": version_id}
        self._governance[file_id] = governance or GovernanceState()

    def bump_version(self, file_id: str, content: bytes, version_id: str) -> None:
        f = self._files[file_id]
        f["content"] = content
        f["version_id"] = version_id

    def list_known_file_ids(self) -> list[str]:
        """All file IDs this client has ever seen (seeded or created via
        companion-doc upload). Used only by the read-only UI listing
        endpoints -- never by the pipeline itself, which always takes an
        explicit file_id."""
        return list(self._files.keys())

    def get_file_name(self, file_id: str) -> str | None:
        f = self._files.get(file_id)
        return f["name"] if f else None

    # -- BoxClient interface -------------------------------------------------------
    def get_file_version(self, file_id: str) -> BoxFileVersion:
        if file_id not in self._files:
            raise BoxAPIError(f"no such file {file_id}")
        f = self._files[file_id]
        sha1 = hashlib.sha1(f["content"]).hexdigest()
        return BoxFileVersion(
            file_id=file_id, version_id=f["version_id"], name=f["name"], sha1=sha1
        )

    def download_file(self, file_id: str) -> bytes:
        if file_id not in self._files:
            raise BoxAPIError(f"no such file {file_id}")
        return self._files[file_id]["content"]

    def get_governance_state(self, file_id: str) -> GovernanceState:
        return self._governance.get(file_id, GovernanceState())

    def get_metadata(self, file_id: str, template_key: str) -> dict[str, Any]:
        return dict(self._metadata.get((file_id, template_key), {}))

    def update_metadata(
        self, file_id: str, template_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        blocked = _PROTECTED_KEYS & set(fields)
        if blocked:
            raise BoxAPIError(
                f"refusing to write governance-protected keys via metadata patch: {blocked}"
            )
        current = self._metadata.setdefault((file_id, template_key), {})
        current.update(fields)
        return dict(current)

    def upload_companion_document(
        self, parent_folder_id: str, filename: str, content: bytes
    ) -> str:
        # Dedupe by (folder, filename): if a retry after a crash asks to
        # upload the same deterministically-named companion again,
        # return the existing file instead of creating a duplicate.
        for existing_id, info in self._files.items():
            if info.get("_companion_folder_id") == parent_folder_id and info.get("name") == filename:
                return existing_id
        self._next_synthetic_id += 1
        new_id = f"companion-{self._next_synthetic_id}"
        self._files[new_id] = {
            "name": filename,
            "content": content,
            "version_id": "1",
            "_companion_folder_id": parent_folder_id,
        }
        self._governance[new_id] = GovernanceState()
        return new_id
