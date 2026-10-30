"""One client, two targets, two transports -- so the assertions can be identical.

The point of a contract suite is that the *same* assertion runs against the mock and
against the live service. If the two paths take different code, the suite proves nothing
about whether they agree. So everything below is about erasing the difference between
`--target mock` and `--target live` at the call site, and being explicit about the two
places where it genuinely cannot be erased:

* **State.** The mock replays a recorded journey; live has to be driven through a real
  one. `Journey` owns that difference so individual tests never see it.
* **Cost.** Live edits spend somebody's operations. Anything that bills is marked
  `billable`, is skipped unless `--allow-billing` is passed, and is counted against a
  hard budget that stops the run rather than grinding through it.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

LIVE_BASE_URL = "https://api.superdocs.app"
KEY_FILE = Path.home() / ".config" / "superdocs" / "api-key"


def load_key() -> str | None:
    key = os.environ.get("SUPERDOCS_API_KEY")
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    return key or None


class BudgetExhausted(RuntimeError):
    pass


@dataclass
class Budget:
    """A hard cap on what one run may spend, checked before each billable call."""

    limit: int
    spent: int = 0
    _charged: set[str] = field(default_factory=set)

    def observe(self, payload: Any) -> None:
        """Count from the response itself, so the number is what was actually billed."""
        if not isinstance(payload, dict):
            return
        usage = payload.get("usage")
        key = payload.get("job_id")
        result = payload.get("result")
        if usage is None and isinstance(result, dict):
            usage = result.get("usage")
            key = key or result.get("session_id")
        if not isinstance(usage, dict) or not usage.get("was_billable"):
            return
        marker = str(key or f"anon-{len(self._charged)}")
        if marker in self._charged:
            return
        self._charged.add(marker)
        self.spent += int(usage.get("ops_charged") or 1)

    def require(self, amount: int = 1) -> None:
        if self.spent + amount > self.limit:
            raise BudgetExhausted(
                f"this run has spent {self.spent} operations and the cap is "
                f"{self.limit}. Raise --op-budget deliberately or trim the run."
            )


class Api:
    """A SuperDocs client that does not care which target it is pointed at."""

    def __init__(
        self,
        base_url: str,
        *,
        target: str,
        transport: str,
        key: str | None,
        budget: Budget,
        scenario: str | None = None,
        run: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.target = target
        self.transport = transport
        self.key = key or "sk_test_contract_suite"
        self.budget = budget
        self.scenario = scenario
        self.run = run
        self.client = httpx.Client(base_url=self.base_url, timeout=120.0)
        self._rpc_id = 0

    def close(self) -> None:
        self.client.close()

    # ---------------------------------------------------------------- headers

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        out = {"Authorization": f"Bearer {self.key}"}
        # Scenario selection is a mock concept. Sending it to live is harmless -- an
        # unknown header is ignored -- but it is only ever set when talking to the mock,
        # so a reader never has to wonder whether live is being steered.
        if self.target == "mock":
            if self.scenario:
                out["X-Mock-Scenario"] = self.scenario
            if self.run:
                out["X-Mock-Run"] = self.run
        if extra:
            out.update(extra)
        return out

    def using(self, scenario: str | None = None, run: str | None = None) -> "Api":
        """Point subsequent calls at a different recorded scenario (mock only)."""
        self.scenario = scenario
        self.run = run or self.run
        return self

    # ---------------------------------------------------------------- REST

    def request(
        self,
        method: str,
        path: str,
        *,
        billable: bool = False,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        if billable and self.target == "live":
            self.budget.require()
        response = self.client.request(
            method, path, headers=self.headers(headers), **kwargs
        )
        if self.target == "live":
            try:
                self.budget.observe(response.json())
            except ValueError:
                pass
        return response

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    # ---------------------------------------------------------------- MCP

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._rpc_id += 1
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": self._rpc_id, "method": method}
        if params is not None:
            body["params"] = params
        response = self.client.post(
            "/mcp/",
            json=body,
            headers=self.headers({
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            }),
        )
        ctype = response.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            import json

            for line in response.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            return {}
        try:
            return response.json()
        except ValueError:
            return {"_status": response.status_code, "_text": response.text}

    def tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call an MCP tool and return its result envelope."""
        payload = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        result = payload.get("result") or {}
        if self.target == "live":
            self.budget.observe(structured(result))
        return result

    def initialize(self) -> dict[str, Any]:
        return (self.rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "sdmock-contract-suite", "version": "0.1.0"},
        }).get("result") or {})


def structured(result: dict[str, Any]) -> Any:
    """Pull the payload out of an MCP tool result, whichever way it was carried."""
    import json

    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                return json.loads(block.get("text", ""))
            except ValueError:
                continue
    return None


@dataclass
class Journey:
    """The four-call contract, driven the way the target needs it driven.

    Against the mock this walks recorded scenarios. Against live it uploads a real
    synthetic document and starts a real job. The *assertions* in the tests are the same
    either way -- which is the entire point.
    """

    api: Api
    session_id: str
    corpus: Path

    def upload(self) -> httpx.Response:
        if self.api.target == "mock":
            self.api.using("styled-document")
            return self.api.post("/v1/documents/upload")
        path = self.corpus / "master-services-agreement.docx"
        with path.open("rb") as fh:
            return self.api.post(
                "/v1/documents/upload",
                files={"file": (path.name, fh, "application/vnd.openxmlformats-"
                                "officedocument.wordprocessingml.document")},
                data={"session_id": self.session_id},
            )

    def start_review(self, message: str = "Tighten the record-keeping clause.") -> str:
        """Begin a review-mode edit and return its job id."""
        if self.api.target == "mock":
            self.api.using("proposed-change-batch")
        body: dict[str, Any] = {
            "message": message,
            "session_id": self.session_id,
            "approval_mode": "ask_every_time",
            "model_tier": "core",
        }
        if self.api.target == "live":
            body["document_html"] = (
                "<h1>Supplier Code of Conduct</h1>"
                "<p>Suppliers shall maintain accurate records for three years.</p>"
                "<p>Suppliers shall report breaches within ten days.</p>"
            )
        response = self.api.post("/v1/chat/async", json=body, billable=True)
        response.raise_for_status()
        return response.json()["job_id"]

    def await_review(self, job_id: str, timeout: float = 240.0) -> dict[str, Any]:
        """Poll until the job pauses for review, and return the job body."""
        deadline = time.perf_counter() + timeout
        while True:
            body = self.api.get(f"/v1/jobs/{job_id}").json()
            if body.get("status") == "awaiting_approval":
                return body
            if body.get("status") in {"completed", "failed", "cancelled"}:
                return body
            if time.perf_counter() > deadline:
                pytest.fail(f"job {job_id} never reached review within {timeout}s")
            if self.api.target == "live":
                time.sleep(3)

    _loaded: bool = False

    def export(self, fmt: str = "docx") -> httpx.Response:
        if self.api.target == "mock":
            self.api.using("export-docx")
        elif not self._loaded:
            # A live session that has never held a document has nothing to export, and
            # says so with a 404. Uploading first is what the four-call contract means;
            # the mock gets this for free because the recording already contains it.
            self.upload()
            self._loaded = True
        return self.api.post(
            "/v1/documents/export",
            json={"session_id": self.session_id, "format": fmt},
        )

    def export_from_empty_session(self) -> httpx.Response:
        """Export before anything is loaded -- a real error path integrators hit.

        Against the mock this reuses the recorded session id so the replay's body
        matching picks the 404 out of the export cassette rather than the 200 sitting
        beside it. Against live any unused id will do, because live really has nothing
        loaded under it.
        """
        session = ("sdmock-empty-session-001" if self.api.target == "mock"
                   else f"{self.session_id}-empty")
        if self.api.target == "mock":
            self.api.using("export-docx")
        return self.api.post(
            "/v1/documents/export",
            json={"session_id": session, "format": "docx"},
        )
