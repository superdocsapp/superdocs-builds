"""The SuperDocs REST client: upload, chat, approve, export.

Four calls are the whole contract with SuperDocs. Everything else in this package is
about deciding what to send.

Two behaviours here come from measurement rather than from the documentation, and both
are written up in ../bug-reports/superdocs-capacity-bugs.html:

* **Capacity is a retry, not a failure.** Both `/v1/chat` and `/v1/chat/async` refuse
  work when the instance is at its concurrent-graph-run limit. The synchronous refusal
  is an honest 503 carrying `retry_after_seconds`; the async one is a job that fails in
  under half a second. Both state that no work was performed, which is what makes an
  automatic re-submit safe rather than reckless — a retry cannot duplicate an edit that
  never happened.
* **Approval is polled, never streamed.** The SSE path delivers proposed changes as a
  JSON string nested inside an already-JSON event, and missing that second parse is the
  documented reason integrators see empty diff cards. Polling `/v1/jobs/{id}` returns
  `metadata.pending_changes` as real objects, so the trap is avoided by construction
  rather than by remembering to parse twice.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

BASE_URL = "https://api.superdocs.app"


class SuperDocsError(RuntimeError):
    pass


class AtCapacity(SuperDocsError):
    """The instance refused the work and performed none of it. Safe to re-submit."""

    def __init__(self, message: str, retry_after: float = 15.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class ProposedChange:
    """One edit awaiting a human decision."""

    change_id: str
    operation: str
    chunk_id: str | None
    old_html: str | None
    new_html: str | None
    explanation: str | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> ProposedChange:
        return cls(
            change_id=raw["change_id"],
            operation=raw.get("operation", "edit"),
            chunk_id=raw.get("chunk_id"),
            old_html=raw.get("old_html"),
            new_html=raw.get("new_html"),
            explanation=raw.get("ai_explanation"),
        )


@dataclass
class Usage:
    """What the run cost, so a report can state it instead of guessing."""

    operations_before: int | None = None
    operations_after: int | None = None
    calls: int = 0
    retries: int = 0
    seconds: float = 0.0
    stages: dict[str, float] = field(default_factory=dict)

    @property
    def operations_spent(self) -> int | None:
        if self.operations_before is None or self.operations_after is None:
            return None
        return self.operations_after - self.operations_before


class Approver(Protocol):
    """Decides each proposed change. The human gate, as a callable.

    Returning (False, "why") rejects the change and hands the reason back to the model,
    which may revise. Rejection has to work, not just acceptance.
    """

    def __call__(self, change: ProposedChange) -> tuple[bool, str | None]: ...


def approve_all(change: ProposedChange) -> tuple[bool, str | None]:
    return True, None


class SuperDocsClient:
    """Thin, synchronous, and deliberately small."""

    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        timeout: float = 300.0,
        max_retries: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise SuperDocsError("no API key: set SUPERDOCS_API_KEY in .env")
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        self.max_retries = max_retries
        self._sleep = sleep
        self.usage = Usage()

    # ------------------------------------------------------------------ plumbing

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SuperDocsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        self.usage.calls += 1
        response = self._http.post(path, json=payload)
        if response.status_code == 503:
            raise AtCapacity(*_capacity_detail(response))
        if response.status_code >= 400:
            raise SuperDocsError(f"POST {path} -> {response.status_code}: {response.text[:400]}")
        return response

    def _get(self, path: str) -> dict[str, Any]:
        self.usage.calls += 1
        response = self._http.get(path)
        if response.status_code >= 400:
            raise SuperDocsError(f"GET {path} -> {response.status_code}: {response.text[:400]}")
        return response.json()

    # --------------------------------------------------------------------- calls

    def whoami(self) -> dict[str, Any]:
        return self._get("/v1/agents/whoami")

    def operations_used(self) -> int | None:
        try:
            return int(self.whoami()["quota"]["used"])
        except Exception:  # noqa: BLE001 - never let accounting break a run
            return None

    def upload_document(self, session_id: str, filename: str, content: str) -> dict[str, Any]:
        """Load the report skeleton as the session's editable document.

        Uploading and parsing is not a billable operation; only the AI edit is.
        """
        payload = {
            "filename": filename,
            "file_base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "session_id": session_id,
            "return_html": True,
        }
        return self._post("/v1/documents/upload-base64", payload).json()

    def upload_image(self, session_id: str, filename: str, image: Path | bytes) -> str:
        """Upload the restoration curve; returns a stable URL for <img src>."""
        raw = image.read_bytes() if isinstance(image, Path) else image
        payload = {
            "filename": filename,
            "image_base64": base64.b64encode(raw).decode("ascii"),
            "session_id": session_id,
        }
        data = self._post("/v1/documents/images/upload-base64", payload).json()
        url = data.get("url")
        if not url:
            raise SuperDocsError(f"image upload returned no url: {data}")
        return url

    def chat(
        self,
        session_id: str,
        message: str,
        approver: Approver = approve_all,
        model_tier: str = "core",
        on_event: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        """Send one edit instruction and run it through the human gate.

        Uses the async path because approval requires it, and polls rather than
        streaming. Re-submits on a capacity refusal, which is safe precisely because
        both refusal shapes state that no work was performed.
        """
        note = on_event or (lambda stage, detail: None)

        for attempt in range(1, self.max_retries + 1):
            try:
                started = self._post(
                    "/v1/chat/async",
                    {
                        "message": message,
                        "session_id": session_id,
                        "approval_mode": "ask_every_time",
                        "model_tier": model_tier,
                    },
                ).json()
            except AtCapacity as exc:
                self.usage.retries += 1
                note("capacity", f"instance busy, retrying in {exc.retry_after:.0f}s (sync refusal)")
                self._sleep(exc.retry_after)
                continue

            job_id = started.get("job_id")
            if not job_id:
                raise SuperDocsError(f"chat_async returned no job_id: {started}")

            try:
                return self._drive_job(session_id, job_id, approver, note)
            except AtCapacity as exc:
                self.usage.retries += 1
                note("capacity", f"job refused at capacity, resubmitting (attempt {attempt})")
                self._sleep(exc.retry_after)
                continue

        raise AtCapacity(
            f"gave up after {self.max_retries} attempts: the instance stayed at capacity. "
            "No edit was applied."
        )

    def _drive_job(
        self,
        session_id: str,
        job_id: str,
        approver: Approver,
        note: Callable[[str, str], None],
    ) -> dict[str, Any]:
        """Poll one job to completion, gating every proposed change through `approver`."""
        decided: set[str] = set()
        started = time.monotonic()

        while True:
            job = self._get(f"/v1/jobs/{job_id}")
            status = job.get("status")

            if status == "completed":
                note("done", f"completed in {time.monotonic() - started:.0f}s")
                return job.get("result") or {}

            if status in ("failed", "cancelled"):
                error = str(job.get("error") or "")
                if "capacity" in error.lower():
                    # The message claims a 120s timeout even when the job died in under
                    # a second; the honest part is "No work was performed", so retry.
                    raise AtCapacity(error)
                raise SuperDocsError(f"job {job_id} {status}: {error}")

            if status == "awaiting_approval":
                meta = job.get("metadata") or {}
                if meta.get("awaiting_kind") == "continue_prompt":
                    note("continue", "large edit paused, continuing")
                    self._post(f"/v1/chat/{session_id}/continue", {"job_id": job_id, "continue": True})
                else:
                    pending = [
                        ProposedChange.from_api(c)
                        for c in (meta.get("pending_changes") or [])
                        if c.get("change_id") not in decided
                    ]
                    if pending:
                        self._decide(session_id, job_id, pending, approver, note)
                        decided.update(c.change_id for c in pending)

            if time.monotonic() - started > 600:
                raise SuperDocsError(f"job {job_id} still {status} after 10 minutes")
            self._sleep(3)

    def _decide(
        self,
        session_id: str,
        job_id: str,
        pending: list[ProposedChange],
        approver: Approver,
        note: Callable[[str, str], None],
    ) -> None:
        """Run the gate over a batch and post the decisions.

        Decisions go in one request carrying per-change verdicts, so rejecting one
        change never discards the rest of the batch.
        """
        decisions: list[dict[str, Any]] = []
        feedback: list[str] = []
        for change in pending:
            ok, why = approver(change)
            entry: dict[str, Any] = {"change_id": change.change_id, "approved": bool(ok)}
            if not ok and why:
                entry["feedback"] = why
                feedback.append(why)
            decisions.append(entry)

        accepted = sum(1 for d in decisions if d["approved"])
        note("gate", f"{accepted} approved, {len(decisions) - accepted} rejected")

        payload: dict[str, Any] = {
            "job_id": job_id,
            # Required at the top level even for batch decisions; omitting it is a 422.
            "approved": True,
            "changes": decisions,
        }
        if feedback:
            payload["feedback"] = " ".join(feedback)
        self._post(f"/v1/chat/{session_id}/approve", payload)

    def export(self, session_id: str, out_path: Path, fmt: str = "docx") -> Path:
        """Export the finished document. Exports never cost operations.

        A4 because the reader is an Indian state regulator, and narrow margins because
        page count is a property of the deliverable: a commission reads a two-page
        after-action report and skims a five-page one.
        """
        self.usage.calls += 1
        response = self._http.post(
            "/v1/documents/export",
            json={
                "session_id": session_id,
                "format": fmt,
                "options": {
                    "filename": out_path.stem,
                    "paper_size": "A4",
                    "margins": "narrow",
                },
            },
        )
        if response.status_code >= 400:
            raise SuperDocsError(f"export -> {response.status_code}: {response.text[:400]}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(response.content)
        return out_path


def _capacity_detail(response: httpx.Response) -> tuple[str, float]:
    try:
        detail = response.json().get("detail", {})
        return (
            str(detail.get("message_user") or "instance at capacity"),
            float(detail.get("retry_after_seconds") or 15),
        )
    except Exception:  # noqa: BLE001
        return "instance at capacity", float(response.headers.get("retry-after") or 15)
