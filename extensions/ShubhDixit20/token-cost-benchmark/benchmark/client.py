"""
Client abstraction over "a model that can edit a document".

This benchmark's two arms both need to send content plus an instruction and
get edited content back, with cost accounting. Two implementations:

  - SuperDocsClient: talks to the REAL SuperDocs REST API, matching the
    contract documented at docs.superdocs.app (verified directly against
    docs.superdocs.app/llms-full.txt — NOT the four-call upload/chat/approve/
    export summary in the task brief, which is a simplified description).
    Needs SUPERDOCS_API_KEY and network access.

  - MockClient: a deterministic, offline stand-in with the same interface.
    Used by tests and small-sample proving runs, per the brief's requirement
    that "real tests exist and run without a live key."

REAL API CONTRACT (verified, corrects earlier assumptions):
  - Endpoint is POST /v1/chat, keyed by `session_id` (a string you choose),
    NOT a document id in the URL path. There is no separate "create
    document" endpoint for raw content — you load content by passing
    `document_html` in the chat call itself.
  - Documents are HTML, not raw markdown/text. `document_html` loads or
    replaces the session's document; omit it on follow-up turns to let the
    server keep working on what it already has.
  - There is NO separate "approve" call needed for this benchmark. Approval
    only applies to the async HITL flow (`chat_async` + `approval_mode=
    'ask_every_time'`). Plain synchronous `/v1/chat` needs no approve step.
  - Export is `POST /v1/documents/export` (POST, not GET), and returns a
    BINARY file body, not JSON. Not needed per-edit for this benchmark —
    only if you want a final exported artifact.
  - The `usage` object in a chat response is about MONTHLY OPERATION
    QUOTAS (monthly_used, ops_charged, monthly_remaining, ...) — it does
    NOT contain per-edit input/output token counts. Real per-edit tokens
    are not exposed by the API at all, so this client keeps the same
    local char-based estimate the mock uses (see metrics.py), applied to
    what was actually sent/received.
  - What IS real and load-bearing: `ops_charged`. SuperDocs bills per
    OPERATION, not per token, and "very large requests count one
    operation per 25 sections edited." A whole-document regenerate on a
    big document can burn many operations in one edit; a section edit
    burns exactly one, regardless of document size. This is the strongest,
    most honest number this benchmark can report for a real run — measured
    straight from the API's own billing field, not estimated pricing.
"""
from __future__ import annotations

import os
import re
import time
import uuid
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
    ops_charged: int = 0  # real, API-billed operation count (0 for mock)


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

        edited_text = content + f"\n\n[edited per: {instruction[:60]}]"
        output_tokens = estimate_tokens(edited_text)

        simulated_latency = (input_tokens / 1000) * self.latency_per_1k_tokens_s
        elapsed = time.perf_counter() - start + simulated_latency

        return EditResult(
            edited_text=edited_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            wall_clock_s=elapsed,
            model="mock-v1",
            source="mock",
            ops_charged=0,
        )


def _markdown_to_minimal_html(text: str) -> str:
    """
    Light, dependency-free markdown -> HTML shim, just enough structure for
    the API to treat the content as a real document (headings + paragraphs)
    rather than one opaque blob. Not a full markdown renderer.

    If you have the `markdown` package available, swap this for
    `markdown.markdown(text)` for better fidelity — noted here rather than
    hidden, per the "configuration over silent workaround" habit used
    elsewhere in this repo.
    """
    lines = text.split("\n")
    html_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            html_lines.append(f"<h{level}>{heading_match.group(2)}</h{level}>")
        else:
            html_lines.append(f"<p>{stripped}</p>")
    return "\n".join(html_lines) or "<p></p>"


def _html_to_text(html: str) -> str:
    """Crude HTML -> text for downstream char/token counting and for the
    whole-doc arm to keep feeding plain-ish content into the next turn."""
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


class SuperDocsClient(BaseClient):
    """
    Real client against the SuperDocs REST API — corrected to match the
    documented contract (docs.superdocs.app), not the earlier four-call
    upload/chat/approve/export guess.

    Each `edit()` call:
      1. Opens a fresh session (uuid4 session_id) and sends `content` as
         `document_html` alongside the instruction, in ONE POST /v1/chat
         call. This mirrors exactly what each arm already does at the
         `arms.py` level: whole_doc passes the full document text every
         turn; section_edit passes only the target section's text every
         turn. The client doesn't need to know which arm it's in — it
         just measures what was sent and what came back, which is the
         benchmark's actual question.
      2. Reads `document_changes.updated_html` from the response as the
         edited content.
      3. Reads `usage.ops_charged` — the REAL, API-billed operation count
         for this edit. This is recorded on EditResult and is the
         strongest "real cost" number this benchmark can report.

    Known simplification, logged rather than hidden: a stronger version of
    the section-edit arm would keep ONE persistent session per document
    and send only natural-language instructions after the first turn
    (relying on the server's persisted state + chunk targeting), sending
    no document_html at all on later turns. This client instead treats
    every edit as a fresh, self-contained exchange, which is a fair and
    conservative approximation but doesn't fully exploit session
    persistence. Worth revisiting if this benchmark's real-mode numbers
    get cited externally.
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
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After", "unknown")
            raise ClientError(
                f"429 rate limited / quota exhausted. Retry-After={retry_after}s. "
                f"Body: {r.text[:300]}"
            )
        r.raise_for_status()
        return r.json()

    def edit(self, content: str, instruction: str) -> EditResult:
        start = time.perf_counter()

        session_id = f"benchmark-{uuid.uuid4().hex[:12]}"
        document_html = _markdown_to_minimal_html(content)

        chat_resp = self._post(
            "/chat",
            json={
                "message": instruction,
                "session_id": session_id,
                "document_html": document_html,
            },
        )

        updated_html = chat_resp.get("document_changes", {}).get("updated_html", "")
        edited_text = _html_to_text(updated_html) if updated_html else content

        elapsed = time.perf_counter() - start

        # Real per-edit token counts are NOT exposed by the API — fall back
        # to the same local estimate the mock uses, applied to what was
        # actually sent/received. This is stated plainly in the README
        # results section, same as the mock-mode caveat.
        input_tokens = estimate_tokens(document_html) + estimate_tokens(instruction)
        output_tokens = estimate_tokens(updated_html or edited_text)

        usage = chat_resp.get("usage", {})
        ops_charged = usage.get("ops_charged", 0)

        return EditResult(
            edited_text=edited_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            wall_clock_s=elapsed,
            model=chat_resp.get("model", "superdocs-default"),
            source="superdocs_api",
            ops_charged=ops_charged,
        )


def get_client(mode: str) -> BaseClient:
    if mode == "mock":
        return MockClient()
    if mode == "real":
        return SuperDocsClient()
    raise ValueError(f"Unknown client mode: {mode!r} (expected 'mock' or 'real')")