"""A small, typed client over the SuperDocs REST surface.

Only the calls the two builds actually make are here. The four-call minimum
contract is ``upload`` -> ``chat`` -> ``approve`` -> ``export``; everything
else on this class is depth one of the builds genuinely needed.

Design notes worth defending out loud:

* **Every billable call goes through the budget.** There is no back door
  that spends an operation without a ledger line.
* **Graceful degradation, twice.** A synchronous ``chat`` that hits a
  gateway timeout is retried on ``/v1/chat/async`` (the documented safe
  path for long work) instead of failing the run. A model tier the account
  cannot use falls back to ``core`` rather than dying.
* **Exports are free**, so the builds export constantly and use the
  exported bytes as evidence.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .budget import OpsBudget
from .changes import Change, changes_from, deep_parse, updated_html_from
from .errors import ApiError, SuperDocsError
from .transport import Transport, build_transport


@dataclass
class ChatResult:
    """What one chat turn produced, already normalised."""

    response_text: str
    session_id: str
    changes: list[Change]
    updated_html: str | None
    version_id: str | None
    changes_summary: str | None
    requires_approval: bool
    job_id: str | None
    ops_charged: int
    seconds: float
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def changed_chunk_ids(self) -> set[str]:
        return {c.chunk_id for c in self.changes if c.chunk_id}


class SuperDocs:
    def __init__(
        self,
        *,
        budget: OpsBudget,
        transport: Transport | None = None,
        cassette_dir: Path | None = None,
        live: bool | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.log = log or (lambda _m: None)
        self.transport = transport or build_transport(
            cassette_dir=cassette_dir, live=live, on_event=self.log
        )
        self.budget = budget

    # ------------------------------------------------------------------
    # account
    # ------------------------------------------------------------------
    def whoami(self) -> dict[str, Any]:
        return self._free("GET", "/v1/agents/whoami", None, "whoami")

    # ------------------------------------------------------------------
    # 1/4 UPLOAD
    # ------------------------------------------------------------------
    def upload_document(
        self,
        *,
        filename: str,
        content: bytes | str,
        session_id: str,
        return_html: bool = False,
    ) -> dict[str, Any]:
        """Load a real file (.docx/.pdf/.md/.html/...) as the session's active
        document. This is a verbatim load: the AI never re-types the content,
        so it cannot come back paraphrased."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        body = {
            "filename": filename,
            "file_base64": base64.b64encode(content).decode("ascii"),
            "session_id": session_id,
            "return_html": return_html,
        }
        return self._free("POST", "/v1/documents/upload-base64", body, f"upload:{filename}")

    def upload_image(self, path: Path, *, content_type: str | None = None) -> str:
        """Upload an image, get back a stable URL to drop into <img src>."""
        data = Path(path).read_bytes()
        body = {
            "image_base64": base64.b64encode(data).decode("ascii"),
            "filename": Path(path).name,
            "content_type": content_type or _guess_type(Path(path).name),
        }
        out = self._free("POST", "/v1/documents/images/upload-base64", body, f"image:{Path(path).name}")
        url = out.get("url") or out.get("image_url") or (out.get("data") or {}).get("url")
        if not url:
            raise SuperDocsError(
                f"Image upload returned no URL. Body keys: {sorted(out)}",
                "Check /v1/documents/images/upload-base64 in openapi.json; the field may "
                "have been renamed.",
            )
        return url

    # ------------------------------------------------------------------
    # sessions and multi-document
    # ------------------------------------------------------------------
    def init_session(self, *, session_id: str | None = None, document_ids: list[str] | None = None):
        body: dict[str, Any] = {}
        if session_id:
            body["session_id"] = session_id
        if document_ids:
            body["document_ids"] = document_ids
        return self._free("POST", "/v1/sessions/init", body, "session-init")

    def list_session_documents(self, session_id: str) -> list[dict[str, Any]]:
        out = self._free("GET", f"/v1/sessions/{session_id}/documents", None, "list-docs")
        docs = out.get("documents") if isinstance(out, dict) else out
        return docs or []

    def open_documents(self, session_id: str, document_ids: list[str]) -> dict[str, Any]:
        return self._free(
            "POST",
            f"/v1/sessions/{session_id}/documents/open",
            {"document_ids": document_ids},
            "open-docs",
        )

    def blank_document(self, session_id: str) -> dict[str, Any]:
        return self._free(
            "POST", f"/v1/sessions/{session_id}/documents/blank", {}, "blank-doc"
        )

    def focus_document(self, session_id: str, document_id: str) -> dict[str, Any]:
        return self._free(
            "POST",
            f"/v1/sessions/{session_id}/documents/{document_id}/focus",
            {},
            "focus-doc",
        )

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self._free("GET", f"/v1/documents/{document_id}", None, "get-doc")

    # ------------------------------------------------------------------
    # 2/4 CHAT  (the only billable call)
    # ------------------------------------------------------------------
    def chat(
        self,
        *,
        session_id: str,
        message: str,
        label: str,
        document_html: str | None = None,
        document_id: str | None = None,
        response_mode: str = "full",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
        approval_mode: str | None = None,
        image_attachments: list[dict[str, Any]] | None = None,
        expected_ops: int = 1,
        timeout: float = 600.0,
    ) -> ChatResult:
        self.budget.check(label, expected_ops)
        body: dict[str, Any] = {"session_id": session_id, "message": message,
                                "response_mode": response_mode}
        for key, val in (
            ("document_html", document_html),
            ("document_id", document_id),
            ("model_tier", model_tier),
            ("thinking_depth", thinking_depth),
            ("approval_mode", approval_mode),
            ("image_attachments", image_attachments),
        ):
            if val is not None:
                body[key] = val

        started = time.monotonic()
        try:
            resp = self.transport.request("POST", "/v1/chat", body, timeout=timeout)
            payload = resp.json_body
            seconds = resp.elapsed_s or (time.monotonic() - started)
        except ApiError as exc:
            if exc.status not in (502, 503, 504):
                raise
            # Graceful degradation: the documented cure for a long sync turn
            # is the async job path, which has no gateway timeout.
            self.log(f"[{label}] sync chat returned {exc.status}; retrying on /v1/chat/async")
            return self._chat_async(body, label=label, timeout=timeout, started=started)

        ops = self.budget.record(label, payload, seconds, note="chat")
        return self._to_result(payload, ops, seconds)

    def _chat_async(self, body: dict[str, Any], *, label: str, timeout: float, started: float) -> ChatResult:
        body = dict(body, async_mode=True)
        resp = self.transport.request("POST", "/v1/chat/async", body, timeout=120)
        job_id = (resp.json_body or {}).get("job_id")
        if not job_id:
            raise SuperDocsError(
                f"/v1/chat/async returned no job_id for '{label}'.",
                "Inspect the response body; the async contract requires job_id.",
            )
        job = self.wait_for_job(job_id, timeout=timeout)
        seconds = time.monotonic() - started
        ops = self.budget.record(label, job, seconds, note="chat_async")
        return self._to_result(job.get("result") or job, ops, seconds, job_id=job_id)

    def chat_async(
        self,
        *,
        session_id: str,
        message: str,
        label: str,
        approval_mode: str = "ask_every_time",
        document_id: str | None = None,
        response_mode: str = "full",
        expected_ops: int = 1,
        **kw: Any,
    ) -> dict[str, Any]:
        """Start a long / human-gated turn. Returns the job envelope."""
        self.budget.check(label, expected_ops)
        body = {
            "session_id": session_id,
            "message": message,
            "async_mode": True,
            "approval_mode": approval_mode,
            "response_mode": response_mode,
        }
        if document_id:
            body["document_id"] = document_id
        body.update({k: v for k, v in kw.items() if v is not None})
        resp = self.transport.request("POST", "/v1/chat/async", body, timeout=120)
        return resp.json_body or {}

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._free("GET", f"/v1/jobs/{job_id}", None, "job-poll", quiet=True)

    def wait_for_job(
        self,
        job_id: str,
        *,
        timeout: float = 900.0,
        stop_on: tuple[str, ...] = ("completed", "failed", "cancelled"),
        poll_s: float = 3.0,
    ) -> dict[str, Any]:
        """Poll a job. Large-document work legitimately runs for minutes with
        no visible progress; that is processing, not a hang."""
        deadline = time.monotonic() + timeout
        last_progress = -1
        while True:
            job = self.get_job(job_id)
            status = job.get("status", "")
            progress = job.get("progress", 0)
            if progress != last_progress:
                self.log(f"  job {job_id[:8]} {status} {progress}%")
                last_progress = progress
            if status in stop_on:
                if status == "failed":
                    raise SuperDocsError(
                        f"Job {job_id} failed: {job.get('error')}",
                        "Re-run the same instruction; if it fails twice the instruction "
                        "is probably ambiguous about which section to change.",
                    )
                return job
            if time.monotonic() > deadline:
                raise SuperDocsError(
                    f"Job {job_id} still '{status}' after {timeout:.0f}s.",
                    "Raise the timeout - multi-minute turns are normal on large "
                    "documents - or cancel with POST /v1/jobs/{job_id}/cancel.",
                )
            time.sleep(poll_s)

    def pending_changes(self, job: dict[str, Any]) -> list[Change]:
        """Proposed changes awaiting a human. Runs the double-parse fix."""
        return changes_from(deep_parse(job))

    # ------------------------------------------------------------------
    # 3/4 APPROVE  (the human gate, exposed as a machine operation)
    # ------------------------------------------------------------------
    def approve(
        self,
        session_id: str,
        job_id: str,
        *,
        decisions: dict[str, bool] | None = None,
        approved: bool | None = None,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """Approve or deny proposed changes, individually or in batch.

        ``decisions`` maps change_id -> approved. Denying one change never
        discards the others.
        """
        body: dict[str, Any] = {"job_id": job_id}
        if decisions is not None:
            body["changes"] = [
                {"change_id": cid, "approved": bool(ok)} for cid, ok in decisions.items()
            ]
            body["approved"] = any(decisions.values())
        else:
            body["approved"] = bool(approved)
        if feedback:
            body["feedback"] = feedback
        return self._free(
            "POST", f"/v1/chat/{session_id}/approve", body, f"approve:{job_id[:8]}"
        )

    # ------------------------------------------------------------------
    # 4/4 EXPORT  (free - so we export as evidence, constantly)
    # ------------------------------------------------------------------
    def export(
        self,
        *,
        session_id: str | None = None,
        html: str | None = None,
        fmt: str = "markdown",
        filename: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> bytes:
        """Export the document. Returns the FILE BYTES.

        The REST endpoint answers with the file itself (``text/markdown``,
        ``text/html``, or the docx media type) plus a Content-Disposition
        header - not a JSON envelope. Assuming JSON here is what made my first
        exports look empty; see bugs.md B1.

        Exports are not billable, which is why the builds in this folder
        export on every single week and use the exported bytes as evidence.
        """
        body: dict[str, Any] = {"format": fmt}
        if session_id:
            body["session_id"] = session_id
        if html:
            body["html"] = html
        opts = dict(options or {})
        if filename:
            opts["filename"] = filename
        if opts:
            body["options"] = opts

        started = time.monotonic()
        resp = self.transport.request("POST", "/v1/documents/export", body, timeout=300)
        seconds = resp.elapsed_s or (time.monotonic() - started)

        if resp.is_json:
            payload = resp.json_body or {}
            # The MCP surface wraps binary formats in a JSON envelope with a
            # short-lived signed URL. REST does not, but handle both.
            url = payload.get("download_url") or payload.get("url")
            if url:
                return self._fetch_url(url)
            for key in ("content", "text", "html", "markdown", "data", "file_content"):
                val = payload.get(key)
                if isinstance(val, str):
                    return val.encode("utf-8")
            raise SuperDocsError(
                f"Export returned a JSON envelope with no file in it: keys={sorted(payload)}",
                "Print the raw body and add its content field to export().",
            )
        self.budget.record_free(f"export:{fmt}", seconds, note="/v1/documents/export")
        return resp.content or b""

    def export_text(self, **kw: Any) -> str:
        return self.export(**kw).decode("utf-8", errors="replace")

    def export_to(self, path: Path, **kw: Any) -> Path:
        data = self.export(**kw)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _fetch_url(self, url: str) -> bytes:
        import httpx

        with httpx.Client(timeout=120) as c:
            return c.get(url).content

    # ------------------------------------------------------------------
    def _free(self, method: str, path: str, body, label: str, quiet: bool = False):
        """A call we believe is non-billable. We still verify: if the server
        reports ops_charged > 0 it goes on the ledger like any other spend."""
        started = time.monotonic()
        resp = self.transport.request(method, path, body, timeout=300)
        seconds = resp.elapsed_s or (time.monotonic() - started)
        payload = resp.json_body
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if usage and (usage.get("ops_charged") or 0) > 0:
            self.budget.record(label, payload, seconds, note=f"unexpected-charge:{path}")
        elif not quiet:
            self.budget.record_free(label, seconds, note=path)
        return payload if payload is not None else {}

    @staticmethod
    def _to_result(payload: dict[str, Any], ops: int, seconds: float, job_id: str | None = None) -> ChatResult:
        payload = payload or {}
        dc = payload.get("document_changes") or {}
        if isinstance(dc, str):
            dc = deep_parse(dc) or {}
        return ChatResult(
            response_text=payload.get("response") or "",
            session_id=payload.get("session_id") or "",
            changes=changes_from(payload),
            updated_html=updated_html_from(payload),
            version_id=dc.get("version_id") if isinstance(dc, dict) else None,
            changes_summary=dc.get("changes_summary") if isinstance(dc, dict) else None,
            requires_approval=bool(dc.get("requires_approval")) if isinstance(dc, dict) else False,
            job_id=job_id,
            ops_charged=ops,
            seconds=seconds,
            raw=payload,
        )


def _guess_type(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower()
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
    }.get(ext, "image/png")
