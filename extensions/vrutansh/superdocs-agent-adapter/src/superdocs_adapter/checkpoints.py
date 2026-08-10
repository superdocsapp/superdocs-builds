"""Atomic, non-secret checkpoints for resumable SuperDocs operations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, InvalidResponseError
from .models import ExportFormat

CHECKPOINT_VERSION = 1


class RunPhase(str, Enum):
    UPLOADED = "uploaded"
    EDITING = "editing"
    APPROVED = "approved"
    COMPLETED = "completed"


@dataclass(frozen=True)
class RunCheckpoint:
    """Minimal durable state; intentionally excludes credentials and document content."""

    version: int
    fingerprint: str
    phase: RunPhase
    session_id: str
    document_id: str | None = None
    job_id: str | None = None
    approved_change_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunCheckpoint:
        try:
            version = int(data["version"])
            if version != CHECKPOINT_VERSION:
                raise InvalidResponseError(
                    f"Unsupported checkpoint version {version}; remove the checkpoint and retry"
                )
            approved = data.get("approved_change_ids") or []
            if not isinstance(approved, list) or not all(
                isinstance(item, str) for item in approved
            ):
                raise TypeError("approved_change_ids must be a list of strings")
            return cls(
                version=version,
                fingerprint=str(data["fingerprint"]),
                phase=RunPhase(str(data["phase"])),
                session_id=str(data["session_id"]),
                document_id=(
                    str(data["document_id"]) if data.get("document_id") is not None else None
                ),
                job_id=str(data["job_id"]) if data.get("job_id") is not None else None,
                approved_change_ids=tuple(approved),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidResponseError(
                "Checkpoint is malformed; inspect or remove it before retrying"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["phase"] = self.phase.value
        data["approved_change_ids"] = list(self.approved_change_ids)
        return data


class FileCheckpointStore:
    """JSON checkpoint store using replace-on-write atomicity on one filesystem."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> RunCheckpoint | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidResponseError(
                f"Could not read checkpoint {self.path}; inspect or remove it before retrying"
            ) from exc
        if not isinstance(data, Mapping):
            raise InvalidResponseError(f"Checkpoint {self.path} must contain a JSON object")
        return RunCheckpoint.from_dict(data)

    def save(self, checkpoint: RunCheckpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload = json.dumps(checkpoint.to_dict(), indent=2, sort_keys=True) + "\n"
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            raise ConfigurationError(
                f"Could not persist checkpoint {self.path}; verify directory permissions"
            ) from exc


def operation_fingerprint(
    file_path: str | Path,
    instruction: str,
    export_format: ExportFormat,
    model_tier: str,
    thinking_depth: str,
) -> str:
    """Hash inputs without retaining document content in the checkpoint."""
    path = Path(file_path)
    if not path.is_file():
        raise ConfigurationError(f"Input document does not exist: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    for value in (instruction, export_format.value, model_tier, thinking_depth):
        digest.update(b"\0")
        digest.update(value.encode("utf-8"))
    return digest.hexdigest()


def checkpoint_name(fingerprint: str) -> str:
    return f"{fingerprint[:20]}.json"
