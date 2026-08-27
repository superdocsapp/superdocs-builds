"""
Client abstraction over "a model that can edit a document".

This benchmark's two arms both need to send a document (or a section of one)
plus an instruction to a model and get edited content back, with token/cost
accounting. Two implementations are provided:

  - SuperDocsClient: talks to the real SuperDocs REST API (upload, chat,
    approve, export — the four-call minimum contract described in the task
    brief) using `requests`. Needs SUPERDOCS_API_KEY and network access.

  - MockClient: a deterministic, offline stand-in with the same interface.
    It does NOT call any network or model — it synthesizes a plausible
    "edited" response and a token/cost estimate using a documented local
    heuristic (see metrics.py). This is what tests and small-sample proving
    runs use, per the brief's requirement that "real tests exist and run
    without a live key."

IMPORTANT: the mock's cost numbers are for proving the harness's *mechanics*
(does it track tokens/cost/time correctly, does the section-edit arm touch
less text than the whole-doc arm, etc.) — they are not a substitute for a
real-API run when reporting actual benchmark results. The README and runner
are explicit about which mode produced which numbers.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from benchmark.metrics import estimate_tokens


@dataclass
class EditResult:
    edited_text: str
    input_tokens: int
    output_tokens: int
    wall_clock_s: float
    model: str
    source: str  # "mock" or "superdocs_api"


class ClientError(RuntimeError):
    pass


class BaseClient:
    name = "base"

    def edit(self, content: str, instruction: str) -> EditResult:
        raise NotImplementedError


class MockClient(BaseClient):
    """Deterministic offline client. No network calls. Safe for CI / no-key runs."""

    name = "mock"

    def __init__(self, latency_per_1k_tokens_s: float = 0.15):
        self.latency_per_1k_tokens_s = latency_per_1k_tokens_s

    def edit(self, content: str, instruction: str) -> EditResult:
        start = time.perf_counter()
        input_tokens = estimate_tokens(content) + estimate_tokens(instruction)

        # Synthesize a plausible edited output: same content with a marker
        # line appended, so downstream code can verify "something changed"
        # without needing a real model. Output length approximates input
        # length (edits mostly preserve length) plus a small delta.
        edited_text = content + f"\n\n[edited per: {instruction[:60]}]"
        output_tokens = estimate_tokens(edited_text)

        # Simulate proportional latency instead of sleeping for real time
        # in tests; callers that want realistic wall-clock can multiply.
        simulated_latency = (input_tokens / 1000) * self.latency_per_1k_tokens_s
        elapsed = time.perf_counter() - start + simulated_latency

        return EditResult(
            edited_text=edited_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            wall_clock_s=elapsed,
            model="mock-v1",
            source="mock",
        )


class SuperDocsClient(BaseClient):
    """
    Real client against the SuperDocs REST API.

    Implements the documented four-call minimum contract:
      1. upload   -> POST /documents
      2. chat     -> POST /documents/{id}/chat        (send edit instruction)
      3. approve  -> POST /documents/{id}/changes/approve
      4. export   -> GET  /documents/{id}/export

    Per the task brief's integration notes:
      - proposed-change content arrives as a JSON-encoded string and needs a
        second json.loads(); the final (post-approve) result is already an
        object. This client performs that second parse.
      - large-document / deep-model operations can take 30s-several minutes
        with no visible progress; this client uses a generous read timeout
        and treats a timeout as "still processing", not a crash — callers
        should retry the status check, not resend the edit (resends cost
        operations).
    """

    name = "superdocs_api"
    BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app/v1")

    def __init__(self, api_key: Optional[str] = None, timeout_s: int = 300):
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise ClientError(
                "SUPERDOCS_API_KEY not set. Real-API mode requires a key; "
                "use --mode mock for offline/small-sample runs."
            )
        self.timeout_s = timeout_s
        try:
            import requests  # local import: keep `requests` optional for mock-only use
        except ImportError as e:
            raise ClientError(
                "The 'requests' package is required for real-API mode "
                "(pip install requests --break-system-packages)."
            ) from e
        self._requests = requests
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def _post(self, path: str, **kwargs):
        r = self._session.post(f"{self.BASE_URL}{path}", timeout=self.timeout_s, **kwargs)
        r.raise_for_status()
        return r.json()

    def _get(self, path: str, **kwargs):
        r = self._session.get(f"{self.BASE_URL}{path}", timeout=self.timeout_s, **kwargs)
        r.raise_for_status()
        return r.json()

    def edit(self, content: str, instruction: str) -> EditResult:
        import json as _json

        start = time.perf_counter()

        upload = self._post("/documents", json={"content": content, "format": "markdown"})
        doc_id = upload["id"]

        chat_resp = self._post(f"/documents/{doc_id}/chat", json={"message": instruction})
        # Documented gotcha: proposed-change content is JSON-encoded twice.
        raw_changes = chat_resp.get("proposed_changes")
        proposed = _json.loads(raw_changes) if isinstance(raw_changes, str) else raw_changes

        approve_resp = self._post(
            f"/documents/{doc_id}/changes/approve",
            json={"change_ids": [c["id"] for c in proposed.get("changes", [])]},
        )

        exported = self._get(f"/documents/{doc_id}/export", params={"format": "markdown"})
        edited_text = exported.get("content", "")

        elapsed = time.perf_counter() - start
        usage = chat_resp.get("usage", {})
        input_tokens = usage.get("input_tokens") or estimate_tokens(content + instruction)
        output_tokens = usage.get("output_tokens") or estimate_tokens(edited_text)

        return EditResult(
            edited_text=edited_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            wall_clock_s=elapsed,
            model=chat_resp.get("model", "unknown"),
            source="superdocs_api",
        )


def get_client(mode: str) -> BaseClient:
    if mode == "mock":
        return MockClient()
    if mode == "real":
        return SuperDocsClient()
    raise ValueError(f"Unknown client mode: {mode!r} (expected 'mock' or 'real')")
