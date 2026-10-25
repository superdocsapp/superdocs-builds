from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable


class UnknownRemoteOutcome(RuntimeError):
    """The caller timed out after the remote operation may have committed."""


@dataclass(frozen=True)
class TransportEvent:
    operation: str
    operation_key: str
    replayed: bool


class FakeSuperDocsTransport:
    """Deterministic local transport with the same retry rule as a paid adapter."""

    def __init__(self) -> None:
        self._results: dict[str, Any] = {}
        self.events: list[TransportEvent] = []
        self._timeouts: set[str] = set()

    def timeout_once(self, operation_key: str) -> None:
        self._timeouts.add(operation_key)

    def call(self, operation: str, operation_key: str, payload: Any, action: Callable[[Any], Any]) -> Any:
        if operation_key in self._results:
            self.events.append(TransportEvent(operation, operation_key, True))
            return deepcopy(self._results[operation_key])
        result = action(payload)
        self._results[operation_key] = deepcopy(result)
        self.events.append(TransportEvent(operation, operation_key, False))
        if operation_key in self._timeouts:
            self._timeouts.remove(operation_key)
            raise UnknownRemoteOutcome(f"unknown outcome for operation key {operation_key}")
        return deepcopy(result)

    def upload(self, operation_key: str, document: dict[str, Any]) -> dict[str, Any]:
        return self.call("upload", operation_key, document, lambda value: {"document": deepcopy(value)})

    def chat(self, operation_key: str, document: dict[str, Any]) -> dict[str, Any]:
        return self.call("chat", operation_key, document, lambda value: {"review": deepcopy(value)})

    def approve(self, operation_key: str, decision: dict[str, Any]) -> dict[str, Any]:
        return self.call("approve", operation_key, decision, lambda value: {"decision": deepcopy(value)})

    def export(self, operation_key: str, document: dict[str, Any]) -> dict[str, Any]:
        return self.call("export", operation_key, document, lambda value: {"artifact": deepcopy(value)})
