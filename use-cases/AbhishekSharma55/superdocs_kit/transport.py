"""HTTP transport, plus record and replay.

Three implementations of one tiny interface:

* ``HttpTransport``     - talks to the live API.
* ``RecordingTransport``- wraps another transport and writes every
                          exchange to a cassette on disk, key redacted.
* ``ReplayTransport``   - serves those cassettes back with no network and
                          no API key, which is what lets the test suite run
                          on a fresh clone.

Recording is deliberately part of the *product* code, not a test helper:
operations cost money, so every live call we ever paid for is kept.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ApiError, ReplayMiss, TransportError
from .secrets import redact

# Fields that legitimately differ between two otherwise identical requests.
# They are excluded from the cassette key so a replay still matches.
_VOLATILE = {"session_id", "user_id", "window_id"}


def request_key(method: str, path: str, body: dict[str, Any] | None) -> str:
    """Stable identity for a request, used as the cassette lookup key."""
    stable = {k: v for k, v in (body or {}).items() if k not in _VOLATILE}
    blob = json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"{method.upper()} {path} {digest}"


@dataclass
class Response:
    status: int
    json_body: Any
    elapsed_s: float = 0.0
    content: bytes | None = None
    content_type: str = ""

    @property
    def is_json(self) -> bool:
        return self.json_body is not None

    def text(self) -> str:
        if self.content is None:
            return ""
        return self.content.decode("utf-8", errors="replace")


class Transport:
    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float = 600.0
    ) -> Response:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class HttpTransport(Transport):
    """Live HTTP with bounded retries.

    Retries only what is safe to retry: connection failures, 429, and 5xx.
    A 4xx other than 429 is a bug in our request and retrying it just burns
    time. Backoff is exponential with jitter so two parallel runs do not
    resonate.
    """

    api_key: str
    base_url: str = "https://api.superdocs.app"
    max_attempts: int = 4
    on_event: Any = None  # optional callable(str) for progress lines

    _client: Any = field(default=None, init=False, repr=False)

    def _http(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "superdocs-builds-abhisheksharma55/1.0",
                },
            )
        return self._client

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float = 600.0
    ) -> Response:
        import httpx

        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                resp = self._http().request(method, path, json=body, timeout=timeout)
            except httpx.HTTPError as exc:  # connect/read/pool errors
                last = TransportError(
                    f"{type(exc).__name__} calling {path}: {redact(str(exc))}",
                    "Large-document operations legitimately take 30s to several minutes; "
                    "raise `timeout` before assuming the server is down.",
                )
                self._sleep(attempt)
                continue

            elapsed = time.monotonic() - started
            if resp.status_code in (429,) or resp.status_code >= 500:
                last = ApiError(resp.status_code, path, resp.text)
                if attempt < self.max_attempts:
                    self._sleep(attempt, resp)
                    continue
                raise last
            if resp.status_code >= 400:
                raise ApiError(resp.status_code, path, resp.text)

            ctype = resp.headers.get("content-type", "")
            # /v1/documents/export answers with the FILE, not a JSON envelope
            # (text/markdown, text/html, or the docx media type). Treating
            # every 200 as JSON is what made my first export attempts return
            # an empty dict - see bugs.md B1, which was my bug, not theirs.
            if "application/json" in ctype:
                return Response(resp.status_code, resp.json(), elapsed, resp.content, ctype)
            return Response(resp.status_code, None, elapsed, resp.content, ctype)

        raise last or TransportError(f"{path} failed with no recorded error", "Retry.")

    def _sleep(self, attempt: int, resp: Any = None) -> None:
        wait = min(30.0, 1.5 * (2 ** (attempt - 1))) + random.uniform(0, 0.6)
        if resp is not None:
            try:
                wait = max(wait, float(resp.headers.get("retry-after", 0)))
            except (TypeError, ValueError):
                pass
        if self.on_event:
            self.on_event(f"retry in {wait:.1f}s (attempt {attempt})")
        time.sleep(wait)


@dataclass
class RecordingTransport(Transport):
    inner: Transport
    cassette_dir: Path

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float = 600.0
    ) -> Response:
        resp = self.inner.request(method, path, body, timeout=timeout)
        self.cassette_dir.mkdir(parents=True, exist_ok=True)
        key = request_key(method, path, body)
        name = hashlib.sha256(key.encode()).hexdigest()[:20] + ".json"
        record = {
            "key": key,
            "method": method.upper(),
            "path": path,
            "request": redact(body or {}),
            "status": resp.status,
            "response": redact(resp.json_body),
            "elapsed_s": round(resp.elapsed_s, 3),
            "content_type": resp.content_type,
        }
        if resp.json_body is None and resp.content is not None:
            if resp.content_type.startswith("text/") or "json" in resp.content_type:
                record["response_text"] = redact(resp.text())
            else:
                record["response_bytes_len"] = len(resp.content)
        (self.cassette_dir / name).write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return resp


@dataclass
class ReplayTransport(Transport):
    """Serves recorded responses. No network, no key, deterministic."""

    cassette_dir: Path
    _index: dict[str, list[dict]] = field(default_factory=dict, init=False)
    calls: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        for f in sorted(Path(self.cassette_dir).glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            self._index.setdefault(rec["key"], []).append(rec)

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float = 600.0
    ) -> Response:
        key = request_key(method, path, body)
        self.calls.append(key)
        hits = self._index.get(key)
        if not hits:
            raise ReplayMiss(
                f"No cassette for {key}",
                f"Record it once against the live API "
                f"(SUPERDOCS_RECORD=1) into {self.cassette_dir}, or fix the request body "
                f"so it matches an existing recording.",
            )
        rec = hits[0] if len(hits) == 1 else hits.pop(0)
        if rec["status"] >= 400:
            raise ApiError(rec["status"], path, json.dumps(rec["response"]))
        text = rec.get("response_text")
        return Response(
            rec["status"],
            rec["response"],
            rec.get("elapsed_s", 0.0),
            content=text.encode("utf-8") if isinstance(text, str) else None,
            content_type=rec.get("content_type", ""),
        )


def build_transport(
    *, cassette_dir: Path | None = None, live: bool | None = None, on_event: Any = None
) -> Transport:
    """One place that decides live vs replay. **Spending has to be asked for.**

    ``live`` must be truthy to reach the network. It used to be three-valued -
    ``None`` meant "decide for me", which meant "look for a key", which meant a
    command a reader would take for a dry run spent five real operations
    (bugs.md M2). Both CLIs were fixed by coercing to ``bool``; this closes the
    same hole for anyone importing the library directly, which is the class
    rather than the two callers that surfaced it.
    """
    from .secrets import api_key, base_url

    if not live:
        return ReplayTransport(cassette_dir or Path("fixtures"))
    key = api_key(required=False)
    if not key:
        from .errors import AuthError

        raise AuthError(
            "live=True was requested but SUPERDOCS_API_KEY is empty.",
            "Put a key in .env, or drop live=True to replay fixtures.",
        )
    http = HttpTransport(api_key=key, base_url=base_url(), on_event=on_event)
    if cassette_dir and os.environ.get("SUPERDOCS_RECORD", "1") != "0":
        return RecordingTransport(http, cassette_dir)
    return http
