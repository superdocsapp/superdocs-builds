"""Gitignored runtime state for resumable live SuperDocs work. Never stores secrets."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from job_architecture.fixtures import PROJECT_ROOT

DEFAULT_STATE_PATH = PROJECT_ROOT / ".runtime" / "live-state.json"

SECRET_KEY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "superdocs_api_key",
        "password",
        "secret",
        "token",
        "bearer",
    }
)


class LiveStateError(ValueError):
    """Runtime state is missing, corrupt, or would leak a secret."""


def _looks_secret_key(name: str) -> bool:
    lowered = name.lower()
    return lowered in SECRET_KEY_NAMES or lowered.endswith("_api_key")


def assert_no_secrets(payload: Any, *, path: str = "state") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if _looks_secret_key(str(key)):
                raise LiveStateError(f"Refusing to store secret field {path}.{key}")
            assert_no_secrets(value, path=f"{path}.{key}")
        return
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            assert_no_secrets(item, path=f"{path}[{index}]")
        return
    if isinstance(payload, str):
        lowered = payload.lower()
        if lowered.startswith("sk_") or "bearer " in lowered:
            raise LiveStateError(f"Refusing to store credential-like value at {path}")


@dataclass
class LiveState:
    session_id: str
    workflow: str = "new"
    completed_steps: list[str] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    templates: dict[str, Any] = field(default_factory=dict)
    jobs: dict[str, Any] = field(default_factory=dict)
    operation_keys: list[str] = field(default_factory=list)
    preservation: dict[str, Any] = field(default_factory=dict)
    profile_integrity: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    domain_apply: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "session_id": self.session_id,
            "workflow": self.workflow,
            "completed_steps": list(self.completed_steps),
            "documents": list(self.documents),
            "templates": dict(self.templates),
            "jobs": dict(self.jobs),
            "operation_keys": list(self.operation_keys),
            "preservation": dict(self.preservation),
            "profile_integrity": dict(self.profile_integrity),
            "verification": dict(self.verification),
            "domain_apply": dict(self.domain_apply),
            "last_error": self.last_error,
        }
        assert_no_secrets(payload)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LiveState:
        assert_no_secrets(data)
        return cls(
            session_id=str(data["session_id"]),
            workflow=str(data.get("workflow") or "new"),
            completed_steps=list(data.get("completed_steps") or []),
            documents=list(data.get("documents") or []),
            templates=dict(data.get("templates") or {}),
            jobs=dict(data.get("jobs") or {}),
            operation_keys=list(data.get("operation_keys") or []),
            preservation=dict(data.get("preservation") or {}),
            profile_integrity=dict(data.get("profile_integrity") or {}),
            verification=dict(data.get("verification") or {}),
            domain_apply=dict(data.get("domain_apply") or {}),
            last_error=data.get("last_error"),
        )

    def mark(self, step: str) -> None:
        if step not in self.completed_steps:
            self.completed_steps.append(step)
        self.workflow = step
        self.last_error = None

    def remember_operation(self, operation_key: str) -> None:
        if operation_key not in self.operation_keys:
            self.operation_keys.append(operation_key)

    def document_for(self, role_id: str) -> dict[str, Any] | None:
        for item in self.documents:
            if item.get("role_id") == role_id or item.get("kind") == role_id:
                return item
        return None


class RuntimeStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_STATE_PATH

    def load(self) -> LiveState | None:
        if not self.path.is_file():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return LiveState.from_dict(payload)

    def save(self, state: LiveState) -> None:
        payload = state.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def load_or_create(self, session_id: str) -> LiveState:
        existing = self.load()
        if existing is None:
            return LiveState(session_id=session_id)
        if existing.session_id != session_id:
            raise LiveStateError(
                f"Saved session {existing.session_id} does not match requested {session_id}"
            )
        return existing
