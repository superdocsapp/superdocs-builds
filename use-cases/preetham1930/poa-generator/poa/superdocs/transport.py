"""How a request reaches SuperDocs - or, in the test suite, how it does not.

Two implementations behind one protocol:

- `HttpTransport` talks to `api.superdocs.app`. It is used by the demo and by
  nothing else. The key is read from the environment, never printed, never
  written to a file, and never included in a message we log.
- `ReplayTransport` answers from recorded responses under `docs/evidence/`. It
  is what the whole test suite runs on, so `make test` passes on a clean
  checkout with no `.env` and with the network blocked (hard rule 3).

A replay transport that is asked for a request it has no recording of **raises**,
naming the request. A transport that invents a plausible response would be the
2026-08-07 failure mode with a different noun: a success message for work that
did not happen.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..errors import NotConfiguredError

DEFAULT_BASE_URL = "https://api.superdocs.app"


class Transport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def download(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> tuple[str, bytes]:
        """For the one endpoint that answers with a file rather than with JSON."""
        ...


def redacted_key() -> str:
    key = os.environ.get("SUPERDOCS_API_KEY", "")
    if not key:
        return "(not set)"
    return f"...{key[-4:]}"


class HttpTransport:
    def __init__(self, base_url: str | None = None, timeout: float = 180.0) -> None:
        self.base_url = (
            base_url or os.environ.get("SUPERDOCS_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = timeout
        self.calls = 0
        key = os.environ.get("SUPERDOCS_API_KEY", "")
        if not key:
            raise NotConfiguredError(
                "SUPERDOCS_API_KEY is not set. This build reads it from .env only, never from "
                "a command line and never from a file it writes. The test suite does not need "
                "it: tests run on recorded responses under docs/evidence/."
            )
        self._key = key

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import httpx  # imported here so the package imports with no network stack

        self.calls += 1
        response = httpx.request(
            method,
            f"{self.base_url}{path}",
            json=json_body,
            params=params,
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            # The body can echo the request; never let it carry the key onward.
            raise RuntimeError(
                f"{method} {path} -> HTTP {response.status_code}. "
                f"{response.text[:400].replace(self._key, '<redacted>')}"
            )
        return response.json()

    def download(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> tuple[str, bytes]:
        """The export endpoint answers with a file, so it does not go through `request`."""
        import httpx

        self.calls += 1
        response = httpx.request(
            method,
            f"{self.base_url}{path}",
            json=json_body,
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"{method} {path} -> HTTP {response.status_code}. "
                f"{response.text[:400].replace(self._key, '<redacted>')}"
            )
        return response.headers.get("content-type", ""), response.content


@dataclass
class RecordedCall:
    method: str
    path: str
    response: dict[str, Any]
    match: dict[str, Any] = field(default_factory=dict)


class ReplayTransport:
    """Answers from recordings, in order, and refuses anything it was not given."""

    def __init__(self, calls: list[RecordedCall]) -> None:
        self._calls = list(calls)
        self.seen: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.seen.append((method, path, json_body))
        for index, call in enumerate(self._calls):
            if call.method != method or call.path != path:
                continue
            if call.match and not all((json_body or {}).get(k) == v for k, v in call.match.items()):
                continue
            self._calls.pop(index)
            return call.response
        raise AssertionError(
            f"no recorded response for {method} {path} with body keys "
            f"{sorted(json_body or {})}. A replay transport never invents one: an invented "
            f"response is a success message for work that did not happen. "
            f"{len(self._calls)} recording(s) left: "
            f"{[(c.method, c.path) for c in self._calls]}"
        )

    def download(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> tuple[str, bytes]:
        """A replayed export records that we asked. There is no file to replay."""
        self.request(method, path, json_body=json_body)
        return "application/octet-stream", b""

    @property
    def exhausted(self) -> bool:
        return not self._calls


def load_recording(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
