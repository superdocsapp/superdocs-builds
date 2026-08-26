"""SuperDocs API client: the four calls this build needs, plus the session and job plumbing.

Two things here exist because of documented traps rather than taste.

1. Proposed-change content arrives as a JSON-encoded string and needs a second parse, while the
   final result is already an object. Missing that is the single most common reason integrators
   see empty diff cards with every field undefined. `parse_change` handles both shapes and is
   tested against both.
2. A single request covers up to twenty-five sections of targeted edits, so edits are batched one
   request per document. Three documents is three operations, not thirteen.
"""

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

import httpx

DEFAULT_BASE = "https://api.superdocs.app"


class SuperDocsError(RuntimeError):
    """Carries the endpoint and the response body, so a failure names its own cause."""


class OperationBudgetExceeded(SuperDocsError):
    """The stopping rule fired. Better a halt you can see than a bill you cannot."""


@dataclass(slots=True)
class ProposedChange:
    change_id: str
    content: dict[str, Any]
    raw: dict[str, Any]

    @property
    def summary(self) -> str:
        for key in ("summary", "description", "title", "reason"):
            value = self.content.get(key) or self.raw.get(key)
            if value:
                return str(value)
        return self.change_id


def parse_change(raw: dict[str, Any]) -> ProposedChange:
    """Normalises one proposed change.

    `content` may arrive as a JSON-encoded string. Parsing it once yields a string that looks like
    an object but indexes as characters, which is what produces cards of undefined fields.
    """
    content: Any = raw.get("content", raw.get("change", {}))
    for _ in range(2):
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = {"text": content}
                break
        else:
            break
    if not isinstance(content, dict):
        content = {"value": content}

    change_id = str(raw.get("change_id") or raw.get("id") or content.get("change_id") or "")
    return ProposedChange(change_id=change_id, content=content, raw=raw)


@dataclass(slots=True)
class JobState:
    job_id: str
    status: str
    changes: list[ProposedChange] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    progress: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def awaiting_review(self) -> bool:
        return self.status in ("awaiting_approval", "awaiting_review", "pending_approval")

    @property
    def finished(self) -> bool:
        return self.status in ("completed", "complete", "succeeded", "failed", "cancelled", "error")


@dataclass(slots=True)
class Usage:
    operations: int = 0
    requests: int = 0
    seconds: float = 0.0


class SuperDocsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE,
        *,
        max_operations: int = 25,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise SuperDocsError(
                "No API key. Fix: set SUPERDOCS_API_KEY in .env. Get one by signing up at "
                "use.superdocs.app, or via the documented agent signup flow."
            )
        self.usage = Usage()
        self._max_operations = max_operations
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # --- plumbing ---

    def _post(self, path: str, payload: dict[str, Any], *, operation: bool = False) -> dict[str, Any]:
        if operation and self.usage.operations >= self._max_operations:
            raise OperationBudgetExceeded(
                f"Stopping: {self.usage.operations} operations already spent against a budget of "
                f"{self._max_operations}. Raise FUND_UPDATE_MAX_OPERATIONS if that is intended."
            )
        started = time.perf_counter()
        response = self._client.post(path, json=payload)
        self.usage.requests += 1
        self.usage.seconds += time.perf_counter() - started
        if operation:
            self.usage.operations += 1
        return self._unwrap(response, path)

    def _get(self, path: str) -> dict[str, Any]:
        started = time.perf_counter()
        response = self._client.get(path)
        self.usage.requests += 1
        self.usage.seconds += time.perf_counter() - started
        return self._unwrap(response, path)

    @staticmethod
    def _unwrap(response: httpx.Response, path: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise SuperDocsError(f"{response.status_code} from {path}: {response.text[:500]}")
        try:
            body = response.json()
        except ValueError:
            return {"raw": response.text}
        return body if isinstance(body, dict) else {"data": body}

    # --- the four calls, plus what they need ---

    def start_session(self) -> str:
        body = self._post("/v1/sessions/init", {})
        session_id = body.get("session_id") or body.get("id")
        if not session_id:
            raise SuperDocsError(f"sessions/init returned no session_id: {str(body)[:300]}")
        return str(session_id)

    def upload_document(self, path: Path, session_id: str | None = None) -> dict[str, Any]:
        """Call 1 of the minimum contract."""
        payload = {
            "filename": path.name,
            "file_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            "return_html": False,
        }
        if session_id:
            payload["session_id"] = session_id
        return self._post("/v1/documents/upload-base64", payload)

    def upload_reference(self, path: Path, session_id: str) -> dict[str, Any]:
        """The new-figures file, uploaded so the model can cite it rather than be told it."""
        return self._post(
            "/v1/attachments/upload-base64",
            {
                "filename": path.name,
                "file_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                "session_id": session_id,
                "return_html": False,
            },
        )

    def request_edit(
        self,
        session_id: str,
        message: str,
        *,
        document_id: str | None = None,
        model_tier: str = "pro",
        thinking_depth: str = "balanced",
    ) -> JobState:
        """Call 2. approval_mode is always ask_every_time: nothing lands without a reviewer."""
        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "async_mode": True,
            "approval_mode": "ask_every_time",
            "model_tier": model_tier,
            "thinking_depth": thinking_depth,
            "response_mode": "full",
        }
        if document_id:
            payload["document_id"] = document_id
        body = self._post("/v1/chat/async", payload, operation=True)
        return JobState(
            job_id=str(body.get("job_id", "")),
            status=str(body.get("status", "queued")),
            raw=body,
        )

    def get_job(self, job_id: str) -> JobState:
        """`result` is null until the job ends, and pending changes live under `metadata`."""
        body = self._get(f"/v1/jobs/{job_id}")
        meta = body.get("metadata") or {}
        result = body.get("result") or {}
        raw_changes = (
            body.get("pending_changes")
            or meta.get("pending_changes")
            or body.get("changes")
            or result.get("changes")
            or []
        )
        notes = [
            str(m.get("content", ""))
            for m in (meta.get("intermediate_responses") or [])
            if isinstance(m, dict)
        ]
        return JobState(
            job_id=job_id,
            status=str(body.get("status", "unknown")),
            changes=[parse_change(c) for c in raw_changes if isinstance(c, dict)],
            result=result,
            raw=body,
            progress=int(body.get("progress") or 0),
            notes=notes,
        )

    def await_job(
        self, job_id: str, *, timeout: float = 900.0, interval: float = 3.0, on_tick=None
    ) -> JobState:
        """Long operations run from thirty seconds to several minutes. Silence is not a crash."""
        deadline = time.monotonic() + timeout
        state = self.get_job(job_id)
        while not state.finished and not state.awaiting_review:
            if time.monotonic() > deadline:
                raise SuperDocsError(
                    f"Job {job_id} still {state.status} after {timeout:.0f}s. It may still be "
                    f"running; check /v1/jobs/{job_id} before retrying, because a retry costs "
                    f"another operation."
                )
            if on_tick:
                on_tick(state)
            time.sleep(interval)
            state = self.get_job(job_id)
        return state

    def decide(
        self,
        session_id: str,
        job_id: str,
        decisions: list[tuple[str, bool, str]],
    ) -> dict[str, Any]:
        """Call 3. Item-by-item: the reviewer approves some and rejects others in one pass."""
        if not decisions:
            return {}
        if len(decisions) == 1:
            change_id, approved, feedback = decisions[0]
            return self._post(
                f"/v1/chat/{session_id}/approve",
                {"job_id": job_id, "change_id": change_id, "approved": approved, "feedback": feedback},
            )
        return self._post(
            f"/v1/chat/{session_id}/approve",
            {
                "job_id": job_id,
                "approved": any(a for _, a, _ in decisions),
                "changes": [
                    {"change_id": cid, "approved": ok, "feedback": note} for cid, ok, note in decisions
                ],
            },
        )

    def export(self, session_id: str, fmt: str = "docx", filename: str | None = None) -> dict[str, Any]:
        """Call 4. Exports never cost operations, so the engine exports freely.

        The response body is the file itself, not JSON, so it never goes through `_unwrap`:
        decoding .docx bytes as text corrupts them silently.
        """
        payload: dict[str, Any] = {"session_id": session_id, "format": fmt}
        if filename:
            payload["filename"] = filename

        started = time.perf_counter()
        response = self._client.post("/v1/documents/export", json=payload)
        self.usage.requests += 1
        self.usage.seconds += time.perf_counter() - started

        if response.status_code >= 400:
            raise SuperDocsError(
                f"{response.status_code} from /v1/documents/export: {response.text[:500]}"
            )
        if "application/json" in response.headers.get("content-type", ""):
            body = response.json()
            return body if isinstance(body, dict) else {"data": body}
        return {"content_bytes": response.content}

    def focus_document(self, session_id: str, document_id: str) -> dict[str, Any]:
        """Which document a session-scoped export applies to."""
        return self._post(f"/v1/sessions/{session_id}/documents/{document_id}/focus", {})

    def whoami(self) -> dict[str, Any]:
        return self._get("/v1/agents/whoami")


def save_export(body: dict[str, Any], destination: Path) -> Path | None:
    """Export responses carry either bytes, base64, or a URL. Handles all three."""
    destination.parent.mkdir(parents=True, exist_ok=True)

    if body.get("content_bytes"):
        destination.write_bytes(body["content_bytes"])
        return destination

    for key in ("file_base64", "content_base64", "data_base64", "base64"):
        if body.get(key):
            destination.write_bytes(base64.b64decode(body[key]))
            return destination

    for key in ("url", "download_url", "file_url", "href"):
        if body.get(key):
            with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                response = client.get(str(body[key]))
                response.raise_for_status()
                destination.write_bytes(response.content)
            return destination

    if isinstance(body.get("html"), str):
        destination.with_suffix(".html").write_text(body["html"], encoding="utf-8")
        return destination.with_suffix(".html")
    return None
