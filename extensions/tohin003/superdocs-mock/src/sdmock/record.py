"""Record mode: capture live SuperDocs traffic into cassettes.

Two shapes, one engine:

* ``Recorder`` performs a call against the live service and appends the interaction to a
  cassette. Scenario scripts drive it directly.
* ``make_proxy_app`` wraps the same recorder in an ASGI app, so an integrator can point an
  existing application at the mock in record mode and capture whatever that application
  actually does. This is the shape the card asks for -- capturing a new scenario should
  not require writing code.

Every interaction is scrubbed on write. Nothing reaches disk unredacted, and the recorder
refuses to run at all if it cannot find a key, rather than silently recording anonymous
401s that would look like a working cassette.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from .cassette import (
    Cassette,
    Interaction,
    RecordedRequest,
    RecordedResponse,
    SSEFrame,
)
from .scrub import KEEP_RESPONSE_HEADERS, scrub_headers, scrub_text, scrub_value

LIVE_BASE_URL = "https://api.superdocs.app"
KEY_FILE = Path.home() / ".config" / "superdocs" / "api-key"

# Request headers worth preserving on a recording. The rest are transport noise.
KEEP_REQUEST_HEADERS = frozenset({"content-type", "accept", "mcp-session-id",
                                  "mcp-protocol-version", "x-mock-scenario"})


def load_key() -> str:
    key = os.environ.get("SUPERDOCS_API_KEY")
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError(
            f"No API key found. Put one in {KEY_FILE} (chmod 600) or set "
            "SUPERDOCS_API_KEY. Record mode will not run without one -- recording "
            "unauthenticated traffic produces a cassette full of 401s that looks "
            "superficially fine."
        )
    return key


class BudgetExceeded(RuntimeError):
    """Raised the moment a recording session would exceed its operation budget."""


class Recorder:
    """Performs live calls and records them, under a hard operation budget."""

    def __init__(
        self,
        *,
        base_url: str = LIVE_BASE_URL,
        budget: int = 50,
        timeout: float = 900.0,
        spec_pin: str = "",
        server: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.key = load_key()
        self.budget = budget
        self.spent = 0
        self._charged: set[str] = set()
        self.spec_pin = spec_pin
        self.server = server
        self.client = httpx.Client(timeout=timeout, follow_redirects=False)
        self.log: list[str] = []

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "Recorder":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def new_cassette(self, scenario: str, description: str, covers: Iterable[str] = ()) -> Cassette:
        return Cassette(
            scenario=scenario,
            description=description,
            covers=list(covers),
            recorded_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            recorded_against={"base_url": self.base_url, "server": self.server},
            spec_pin=self.spec_pin,
        )

    # ------------------------------------------------------------------ recording

    def auth_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.key}"}
        if extra:
            headers.update(extra)
        return headers

    def _charge(self, response_json: Any) -> bool:
        """Count an operation if the response says it billed one, exactly once.

        A completed job repeats its `usage` block on every subsequent poll, so a naive
        counter bills the same work again on each poll -- it read 27 for 9 operations
        actually spent before this was fixed. Charges are keyed by job id, and by
        session plus counter for synchronous turns that carry no job.
        """
        usage = None
        job_key = None
        if isinstance(response_json, dict):
            usage = response_json.get("usage")
            job_key = response_json.get("job_id")
            result = response_json.get("result")
            if usage is None and isinstance(result, dict):
                usage = result.get("usage")
                job_key = job_key or result.get("session_id")
        if not isinstance(usage, dict) or not usage.get("was_billable"):
            return False

        key = str(job_key) if job_key else f"anon-{len(self._charged)}"
        if key in self._charged:
            return False
        self._charged.add(key)
        self.spent += int(usage.get("ops_charged") or 1)
        return True

    def _send_with_retry(
        self, method: str, url: str, *, attempts: int = 4, **kwargs: Any
    ) -> httpx.Response:
        """Send, retrying only transport-level failures.

        A long recording session polls a job for minutes, and a connection will
        occasionally be dropped by an intermediary -- which is not the same thing as the
        request having failed. Retrying the poll is safe because it is a GET; anything
        that could bill twice is not retried, so a dropped response never turns into a
        double charge.

        This exists because it bit: a 400-section edit polled for several minutes and
        died on `RemoteProtocolError: Server disconnected without sending a response`,
        losing a recording that had already cost 16 operations.
        """
        idempotent = method.upper() in {"GET", "HEAD", "OPTIONS"}
        delay = 1.0
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                return self.client.request(method, url, **kwargs)
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError,
                    httpx.ReadTimeout, httpx.WriteError) as exc:
                last = exc
                if not idempotent or attempt == attempts - 1:
                    break
                print(f"    (transport hiccup on {method} {url.rsplit('/', 1)[-1]}: "
                      f"{type(exc).__name__}; retrying in {delay:.0f}s)")
                time.sleep(delay)
                delay *= 2
        assert last is not None
        raise last

    def check_budget(self, about_to_spend: int = 1) -> None:
        if self.spent + about_to_spend > self.budget:
            raise BudgetExceeded(
                f"recording would spend operation {self.spent + about_to_spend} of a "
                f"{self.budget} budget -- stopping. Raise the budget deliberately or "
                "trim the scenario."
            )

    def call(
        self,
        cassette: Cassette,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        transport: str = "rest",
        note: str = "",
        expect_billable: bool = False,
    ) -> httpx.Response:
        """Perform one live call and append it to the cassette."""
        if expect_billable:
            self.check_budget()

        url = f"{self.base_url}{path}"
        request_headers = self.auth_headers(headers)
        started = time.perf_counter()
        response = self._send_with_retry(
            method, url,
            json=json_body, files=files, data=data, headers=request_headers,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        parsed: Any | None = None
        text_body: str | None = None
        b64_body: str | None = None
        ctype = response.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                parsed = response.json()
            except ValueError:
                text_body = response.text
        elif ctype.startswith("text/") or not response.content:
            text_body = response.text
        else:
            import base64 as _b64

            b64_body = _b64.b64encode(response.content).decode("ascii")

        billable = self._charge(parsed)

        multipart = None
        if files:
            multipart = [
                {"field": field, "filename": getattr(value, "name", "<bytes>")}
                for field, value in files.items()
            ]

        interaction = Interaction(
            id=f"i-{len(cassette.interactions) + 1:03d}",
            transport=transport,
            request=RecordedRequest(
                method=method.upper(),
                path=path,
                headers=scrub_headers(request_headers, keep=KEEP_REQUEST_HEADERS),
                json_body=scrub_value(json_body) if json_body is not None else None,
                multipart=multipart,
            ),
            response=RecordedResponse(
                status=response.status_code,
                headers=scrub_headers(dict(response.headers), keep=KEEP_RESPONSE_HEADERS),
                json_body=scrub_value(parsed) if parsed is not None else None,
                text_body=scrub_text(text_body) if text_body is not None else None,
                base64_body=b64_body,
            ),
            elapsed_ms=elapsed_ms,
            billable=billable,
            note=note,
        )
        cassette.interactions.append(interaction)

        marker = f" [+{self.spent} ops]" if billable else ""
        line = f"    {method:6s} {path:52s} -> {response.status_code} ({elapsed_ms} ms){marker}"
        self.log.append(line)
        print(line)
        return response

    def stream(
        self,
        cassette: Cassette,
        session_id: str,
        job_id: str,
        *,
        max_seconds: float = 600.0,
        stop_on: frozenset[str] = frozenset({"final", "error"}),
        last_sequence: int | None = None,
        note: str = "",
    ) -> list[SSEFrame]:
        """Capture the SSE stream for a job, frame by frame, with arrival offsets.

        Auth rides the query string because EventSource cannot set headers (B-004), so
        the recorded path is scrubbed before it is written.
        """
        path = f"/v1/chat/{session_id}/stream"
        query: dict[str, Any] = {"job_id": job_id, "api_key": self.key}
        if last_sequence is not None:
            query["last_sequence"] = last_sequence
        url = f"{self.base_url}{path}"

        frames: list[SSEFrame] = []
        started = time.perf_counter()
        event_name = "message"
        status = 0
        headers: dict[str, str] = {}

        with self.client.stream("GET", url, params=query) as response:
            status = response.status_code
            headers = dict(response.headers)
            for raw in response.iter_lines():
                if time.perf_counter() - started > max_seconds:
                    self.log.append("    (stream capture hit its time cap)")
                    break
                line = raw.rstrip("\r")
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    payload = line[5:].strip()
                    sequence = None
                    try:
                        import json as _json

                        decoded = _json.loads(payload)
                        if isinstance(decoded, dict):
                            raw_seq = decoded.get("sequence")
                            sequence = int(raw_seq) if raw_seq is not None else None
                    except (ValueError, TypeError):
                        pass
                    frames.append(
                        SSEFrame(
                            event=event_name,
                            data=scrub_text(payload),
                            offset_ms=int((time.perf_counter() - started) * 1000),
                            sequence=sequence,
                        )
                    )
                    if event_name in stop_on:
                        break
                    event_name = "message"

        cassette.interactions.append(
            Interaction(
                id=f"i-{len(cassette.interactions) + 1:03d}",
                transport="rest",
                request=RecordedRequest(
                    method="GET",
                    path=path,
                    query={"job_id": job_id, "api_key": "[REDACTED]"},
                    headers={"accept": "text/event-stream"},
                ),
                response=RecordedResponse(
                    status=status,
                    headers=scrub_headers(headers, keep=KEEP_RESPONSE_HEADERS),
                    sse=frames,
                ),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                note=note,
            )
        )
        print(f"    SSE    {path:52s} -> {status} ({len(frames)} frames)")
        return frames

    # ------------------------------------------------------------------ MCP

    def mcp(
        self,
        cassette: Cassette,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        protocol: str = "2025-06-18",
        rpc_id: int = 1,
        note: str = "",
        expect_billable: bool = False,
    ) -> dict[str, Any]:
        """Perform one MCP JSON-RPC call over Streamable HTTP and record it."""
        if expect_billable:
            self.check_budget()

        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
        if params is not None:
            payload["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": protocol,
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        started = time.perf_counter()
        response = self.client.post(
            f"{self.base_url}/mcp/", json=payload, headers=self.auth_headers(headers)
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        body: Any
        ctype = response.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            body = None
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    import json as _json

                    body = _json.loads(line[5:].strip())
                    break
        else:
            try:
                body = response.json()
            except ValueError:
                body = None

        billable = False
        if isinstance(body, dict):
            billable = self._charge(_mcp_payload(body))

        cassette.interactions.append(
            Interaction(
                id=f"i-{len(cassette.interactions) + 1:03d}",
                transport="mcp",
                request=RecordedRequest(
                    method="POST",
                    path="/mcp/",
                    headers=scrub_headers(headers, keep=KEEP_REQUEST_HEADERS),
                    json_body=scrub_value(payload),
                ),
                response=RecordedResponse(
                    status=response.status_code,
                    headers=scrub_headers(dict(response.headers), keep=KEEP_RESPONSE_HEADERS),
                    json_body=scrub_value(body) if body is not None else None,
                    text_body=None if body is not None else scrub_text(response.text),
                ),
                elapsed_ms=elapsed_ms,
                billable=billable,
                note=note or method,
            )
        )
        marker = f" [+{self.spent} ops]" if billable else ""
        print(f"    MCP    {method:52s} -> {response.status_code} ({elapsed_ms} ms){marker}")
        return body if isinstance(body, dict) else {}


def _mcp_payload(body: dict[str, Any]) -> Any:
    """Dig the tool result out of an MCP envelope so usage can be counted."""
    result = body.get("result")
    if not isinstance(result, dict):
        return None
    content = result.get("structuredContent")
    if isinstance(content, dict):
        return content
    blocks = result.get("content")
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                import json as _json

                try:
                    return _json.loads(block.get("text", ""))
                except ValueError:
                    continue
    return None
