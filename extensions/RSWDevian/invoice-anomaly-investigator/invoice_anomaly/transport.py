from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class UnknownRemoteOutcome(RuntimeError):
    """The caller must retry the same operation key to reconcile the result."""


@dataclass(frozen=True)
class Event:
    operation: str
    operation_key: str
    replayed: bool


class LocalSuperDocsTransport:
    """Fixture transport for upload/chat/approve/export idempotency tests."""

    def __init__(self) -> None:
        self._results: dict[str, dict[str, Any]] = {}
        self._timeouts: set[str] = set()
        self.events: list[Event] = []

    def timeout_once(self, operation_key: str) -> None:
        self._timeouts.add(operation_key)

    def _call(self, operation: str, operation_key: str, result: dict[str, Any]) -> dict[str, Any]:
        if operation_key in self._results:
            self.events.append(Event(operation, operation_key, True))
            return self._results[operation_key]
        if operation_key in self._timeouts:
            self._timeouts.remove(operation_key)
            # The remote side committed before the response was lost. Keeping
            # the result makes a same-key retry a reconciliation, not a repeat.
            self._results[operation_key] = result
            self.events.append(Event(operation, operation_key, False))
            raise UnknownRemoteOutcome(f"unknown outcome for {operation_key}; retry with the same key")
        self._results[operation_key] = result
        self.events.append(Event(operation, operation_key, False))
        return result

    def upload(self, operation_key: str, source_hash: str) -> dict[str, Any]:
        return self._call("upload", operation_key, {"source_hash": source_hash, "uploaded": True})

    def chat(self, operation_key: str, prompt: str) -> dict[str, Any]:
        return self._call("chat", operation_key, {"prompt": prompt, "completed": True})

    def approve(self, operation_key: str, decision: str) -> dict[str, Any]:
        return self._call("approve", operation_key, {"decision": decision, "recorded": True})

    def export(self, operation_key: str, artifact_hash: str) -> dict[str, Any]:
        return self._call("export", operation_key, {"artifact_hash": artifact_hash, "exported": True})
