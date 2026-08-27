"""Async client for the SuperDocs REST surface.

Covers the four calls the task brief names as the minimum contract, upload,
chat, approve, export, plus the image and template endpoints this build needs.

Behaviour here follows what the live API actually did during integration, which
differs from the documentation in one place worth knowing: on
``GET /v1/jobs/{id}`` the ``pending_changes`` entries arrive as real JSON
objects, not the JSON-encoded strings the integrator notes warn about. We parse
defensively either way, because a surface that changes shape under you should
not take the report down with it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import pathlib
import random
from dataclasses import dataclass
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://api.superdocs.app"
CREDENTIALS_PATH = pathlib.Path.home() / ".superdocs" / "agent_credentials.json"

ExportFormat = Literal["docx", "pdf", "html", "markdown", "txt", "doc"]


class SuperDocsError(RuntimeError):
    """An API call failed in a way the caller needs to know about.

    Carries the cause and, where there is one, the fix, a bare status code in
    a log at 2am helps nobody.
    """

    def __init__(self, message: str, *, status: int | None = None, fix: str | None = None):
        self.status = status
        self.fix = fix
        super().__init__(f"{message}" + (f", {fix}" if fix else ""))


class QuotaExhausted(SuperDocsError):
    """The account is out of monthly operations."""


@dataclass(frozen=True, slots=True)
class ProposedChange:
    """One edit the model wants to make, awaiting a human decision."""

    change_id: str
    operation: Literal["edit", "create", "delete"]
    chunk_id: str | None
    old_html: str | None
    new_html: str | None
    ai_explanation: str
    insert_after_chunk_id: str | None = None

    @classmethod
    def parse(cls, raw: Any) -> ProposedChange:
        # The documented double-encoding hazard: tolerate a JSON string here.
        if isinstance(raw, str):
            raw = json.loads(raw)
        return cls(
            change_id=raw["change_id"],
            operation=raw.get("operation", "edit"),
            chunk_id=raw.get("chunk_id"),
            old_html=raw.get("old_html"),
            new_html=raw.get("new_html"),
            ai_explanation=raw.get("ai_explanation", ""),
            insert_after_chunk_id=raw.get("insert_after_chunk_id"),
        )


@dataclass(frozen=True, slots=True)
class JobState:
    job_id: str
    status: str
    session_id: str | None
    awaiting_kind: str | None
    pending_changes: list[ProposedChange]
    result: dict[str, Any] | None

    @property
    def is_change_review(self) -> bool:
        """True when the job is paused for change approval, not a continue prompt.

        The API uses one status for both; branching on ``awaiting_kind`` first
        is required, because calling /approve on a continue prompt returns 409.
        """
        return self.status == "awaiting_approval" and self.awaiting_kind != "continue_prompt"


def load_api_key(explicit: str | None = None) -> str:
    """Resolve the API key from an argument, the environment, or the agent file."""
    import os

    key = explicit or os.environ.get("SUPERDOCS_API_KEY")
    if key:
        return key
    if CREDENTIALS_PATH.exists():
        try:
            return json.loads(CREDENTIALS_PATH.read_text())["api_key"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise SuperDocsError(
                f"{CREDENTIALS_PATH} exists but has no usable api_key",
                fix="delete it and re-run agent signup, or set SUPERDOCS_API_KEY",
            ) from exc
    raise SuperDocsError(
        "no SuperDocs API key found",
        fix=(
            "set SUPERDOCS_API_KEY, or POST /v1/agents/signup and save the response "
            f"to {CREDENTIALS_PATH}"
        ),
    )


class SuperDocsClient:
    """Thin, retrying async wrapper over the endpoints this build uses."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        timeout: float = 300.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = load_api_key(api_key)
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout, connect=15.0),
            headers={"Authorization": f"Bearer {self._key}"},
            transport=transport,
        )

    async def __aenter__(self) -> SuperDocsClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---------------------------------------------------------------- plumbing

    async def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        """Issue a request, retrying only what is safe to retry.

        429 and 5xx get exponential backoff with jitter. 4xx other than 429 are
        returned to the caller immediately, retrying a malformed body just
        burns wall-clock and, on billable paths, money.
        """
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.request(method, path, **kw)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if attempt == self._max_retries - 1:
                    break
                await self._backoff(attempt)
                continue

            if response.status_code < 400:
                return response
            if response.status_code == 402 or self._is_quota(response):
                raise QuotaExhausted(
                    "SuperDocs monthly operation limit reached",
                    status=response.status_code,
                    fix="POST /v1/agents/handoff to let a human adopt and upgrade the account",
                )
            if response.status_code == 429 or response.status_code >= 500:
                last = SuperDocsError(
                    f"{method} {path} returned {response.status_code}",
                    status=response.status_code,
                )
                if attempt == self._max_retries - 1:
                    break
                await self._backoff(attempt, response)
                continue

            raise SuperDocsError(
                f"{method} {path} returned {response.status_code}: {response.text[:400]}",
                status=response.status_code,
                fix=_fix_for(response.status_code),
            )

        raise SuperDocsError(
            f"{method} {path} failed after {self._max_retries} attempts: {last}"
        ) from last

    @staticmethod
    def _is_quota(response: httpx.Response) -> bool:
        if response.status_code != 403:
            return False
        return "quota" in response.text.lower() or "operation limit" in response.text.lower()

    @staticmethod
    async def _backoff(attempt: int, response: httpx.Response | None = None) -> None:
        if response is not None and (retry_after := response.headers.get("Retry-After")):
            try:
                await asyncio.sleep(min(float(retry_after), 60.0))
                return
            except ValueError:
                pass
        await asyncio.sleep(min(2**attempt, 16) + random.uniform(0, 0.5))

    async def _json(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        return (await self._request(method, path, **kw)).json()

    # ------------------------------------------------------------------ calls

    async def whoami(self) -> dict[str, Any]:
        return await self._json("GET", "/v1/agents/whoami")

    async def remaining_operations(self) -> int:
        return int((await self.whoami())["quota"]["remaining"])

    async def upload_document(
        self, content: bytes, filename: str, session_id: str
    ) -> dict[str, Any]:
        """Upload a file as the session's active editable document."""
        return await self._json(
            "POST",
            "/v1/documents/upload",
            files={"file": (filename, content)},
            data={"session_id": session_id},
        )

    async def upload_template(self, content: bytes, filename: str) -> dict[str, Any]:
        """Register a firm template the model can start new documents from."""
        return await self._json(
            "POST", "/v1/templates/upload", files={"file": (filename, content)}
        )

    async def list_templates(self) -> list[dict[str, Any]]:
        payload = await self._json("GET", "/v1/templates")
        return payload if isinstance(payload, list) else payload.get("templates", [])

    async def upload_image(self, png: bytes, filename: str = "chart.png") -> str:
        """Store a chart and return the stable URL to reference from ``<img src>``."""
        payload = await self._json(
            "POST",
            "/v1/documents/images/upload-base64",
            json={
                "image_base64": base64.b64encode(png).decode(),
                "filename": filename,
            },
        )
        url = payload.get("url") or payload.get("image_url") or payload.get("src")
        if not url:
            raise SuperDocsError(
                f"image upload returned no URL: {json.dumps(payload)[:300]}",
                fix="check the /v1/documents/images/upload-base64 response shape",
            )
        return url

    async def start_chat(
        self,
        message: str,
        session_id: str,
        *,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
    ) -> str:
        """Start an async chat turn and return its job id.

        Always async: the sync endpoint hits a ~300s gateway timeout, and a
        report-length turn is exactly the kind of request that reaches it.
        """
        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }
        if document_html is not None:
            body["document_html"] = document_html
        if model_tier:
            body["model_tier"] = model_tier
        return (await self._json("POST", "/v1/chat/async", json=body))["job_id"]

    async def get_job(self, job_id: str) -> JobState:
        raw = await self._json("GET", f"/v1/jobs/{job_id}")
        meta = raw.get("metadata") or {}
        pending = meta.get("pending_changes") or []
        if isinstance(pending, str):
            pending = json.loads(pending)
        result = raw.get("result")
        if isinstance(result, str):
            result = json.loads(result)
        return JobState(
            job_id=raw.get("job_id", job_id),
            status=raw.get("status", "unknown"),
            session_id=raw.get("session_id"),
            awaiting_kind=meta.get("awaiting_kind"),
            pending_changes=[ProposedChange.parse(c) for c in pending],
            result=result,
        )

    async def wait_for_job(
        self,
        job_id: str,
        *,
        poll_seconds: float = 3.0,
        timeout_seconds: float = 900.0,
    ) -> JobState:
        """Poll until the job needs us or finishes.

        Long silences are normal on this API, a deep edit on a large document
        can run for minutes with no visible progress, so the timeout is
        generous and the loop reports rather than guesses.
        """
        waited = 0.0
        while waited < timeout_seconds:
            state = await self.get_job(job_id)
            if state.status in ("awaiting_approval", "completed", "failed", "cancelled"):
                return state
            await asyncio.sleep(poll_seconds)
            waited += poll_seconds
        raise SuperDocsError(
            f"job {job_id} did not settle within {timeout_seconds:.0f}s",
            fix="poll GET /v1/jobs/{job_id} directly, or cancel it via /v1/jobs/{job_id}/cancel",
        )

    async def continue_chat(self, session_id: str, job_id: str, keep_going: bool = True) -> dict[str, Any]:
        """Answer a large-edit continue prompt.

        A long turn applies what it can, keeps that work, and pauses to ask
        whether to spend more. This is a *different* pause from change review
        and takes a different endpoint, calling /approve here returns 409.
        """
        return await self._json(
            "POST",
            f"/v1/chat/{session_id}/continue",
            json={"job_id": job_id, "continue": keep_going},
        )

    async def cancel_job(self, job_id: str) -> None:
        """Discard a paused or running job so its session is usable again.

        A job left paused makes the whole session refuse new instructions with
        ``session_busy``. Cancelling on the way out of a failure is what keeps
        one bad turn from bricking the report.
        """
        try:
            await self._request("POST", f"/v1/jobs/{job_id}/cancel")
        except SuperDocsError as exc:
            log.warning("could not cancel job %s: %s", job_id, exc)

    async def approve(
        self,
        session_id: str,
        job_id: str,
        decisions: dict[str, bool],
        *,
        feedback: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Record a per-change human decision.

        ``approved`` is required at the top level even when every entry carries
        its own, omitting it is rejected with an opaque 422.
        """
        if not decisions:
            raise ValueError("approve() needs at least one decision")
        feedback = feedback or {}
        changes = [
            {"change_id": cid, "approved": ok, **({"feedback": feedback[cid]} if cid in feedback else {})}
            for cid, ok in decisions.items()
        ]
        body = {"job_id": job_id, "approved": any(decisions.values()), "changes": changes}
        return await self._json("POST", f"/v1/chat/{session_id}/approve", json=body)

    async def save_document(
        self,
        session_id: str,
        document_id: str,
        html: str,
        *,
        base_html: str | None = None,
        touched_chunk_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Persist an edit we made ourselves, without invoking the model.

        This is the zero-cost path. When a re-run only needs new *values* in
        prose that still reads correctly, the substitution happens locally and
        lands here, no operation is billed, which is what lets an update cost
        like an update. ``touched_chunk_ids`` keeps the write scoped to the
        sections that actually moved.
        """
        body: dict[str, Any] = {"html": html}
        if base_html is not None:
            body["base_html"] = base_html
        if touched_chunk_ids:
            body["touched_chunk_ids"] = touched_chunk_ids
        return await self._json(
            "POST", f"/v1/sessions/{session_id}/documents/{document_id}/save", json=body
        )

    async def export(
        self,
        *,
        session_id: str | None = None,
        html: str | None = None,
        fmt: ExportFormat = "docx",
        filename: str = "report",
        options: dict[str, Any] | None = None,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Render the document and return ``(bytes, non_fatal_warnings)``.

        Exports do not consume operations, so this is the cheap way to check
        what the document actually looks like.
        """
        if not session_id and not html:
            raise ValueError("export needs either session_id or html")
        body: dict[str, Any] = {"format": fmt, "filename": filename}
        if session_id:
            body["session_id"] = session_id
        if html:
            body["html"] = html
        if options:
            body["options"] = options

        response = await self._request("POST", "/v1/documents/export", json=body)
        warnings: list[dict[str, Any]] = []
        if header := response.headers.get("X-Export-Warnings"):
            try:
                warnings = json.loads(base64.b64decode(header))
            except (ValueError, json.JSONDecodeError):
                log.warning("could not decode X-Export-Warnings header")
        return response.content, warnings


def _fix_for(status: int) -> str | None:
    return {
        401: "the API key is missing or revoked, check SUPERDOCS_API_KEY",
        404: "the session or job does not exist; session ids are chosen by you and are per-account",
        409: "the job is paused for a different reason, branch on metadata.awaiting_kind first",
        413: "payload too large, use the pre-signed upload flow for HTML above 20 MB",
        422: "request body rejected, /approve requires a top-level 'approved' field",
    }.get(status)
