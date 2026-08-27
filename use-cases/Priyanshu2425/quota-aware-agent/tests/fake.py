"""A fake SuperDocs. Every response shape here is taken from the documented
payloads, including the double-parsed proposed-change envelope."""

from __future__ import annotations

import json

from quota_aware_agent.client import Response


class FakeSuperDocs:
    def __init__(self, remaining: int = 500, monthly_limit: int = 500,
                 sections_per_edit: int = 1, slow_polls: int = 0,
                 exhaust_after: int | None = None, settle_polls: int = 1,
                 envelope_pending: bool = False) -> None:
        self.remaining = remaining
        self.monthly_limit = monthly_limit
        self.sections_per_edit = sections_per_edit
        self.slow_polls = slow_polls
        self.exhaust_after = exhaust_after
        self.settle_polls = settle_polls
        self.envelope_pending = envelope_pending
        self._approved_at_poll: int | None = None
        self.calls: list[tuple[str, str]] = []
        self._polls = 0
        self._edits = 0
        self.approved: list[dict] = []
        self.uploaded: list[str] = []

    # -- helpers ----------------------------------------------------------
    def _usage(self, ops: int) -> dict:
        self.remaining = max(0, self.remaining - ops)
        exhausted = (
            self.exhaust_after is not None and self._edits >= self.exhaust_after
        ) or self.remaining == 0
        return {
            "monthly_used": self.monthly_limit - self.remaining,
            "monthly_limit": self.monthly_limit,
            "monthly_remaining": self.remaining,
            "was_billable": ops > 0,
            "ops_charged": ops,
            "quota_exhausted": exhausted,
            "subscription_tier": "free",
        }

    # -- transport --------------------------------------------------------
    def request(self, method: str, path: str, **kw) -> Response:
        self.calls.append((method, path))

        if path == "/v1/agents/whoami":
            return Response(200, {
                "account_id": "fake",
                "quota": {"tier": "free", "monthly_limit": self.monthly_limit,
                          "used": self.monthly_limit - self.remaining,
                          "remaining": self.remaining,
                          "resets_at": "2026-09-01T00:00:00+00:00"},
            })

        if path == "/v1/documents/upload":
            # The real endpoint answers 422 when the multipart `file` part is
            # absent. Modelled here because a fake that accepts anything is how
            # a transport that encoded nothing passed its tests.
            files = kw.get("files") or {}
            if "file" not in files:
                return Response(422, {"detail": [
                    {"type": "missing", "loc": ["body", "file"], "msg": "Field required"}
                ]})
            name, body = files["file"]
            # The live API parses by EXTENSION, not by sniffing the bytes: HTML
            # sent as report.docx is answered 400. Modelled here because a fake
            # that accepts any filename is how the demo shipped uploading HTML
            # under a .docx name and nobody found out until a live run.
            # Verified against the live API 2026-08-20.
            if (str(name).lower().endswith((".docx", ".xlsx", ".pptx", ".odt"))
                    and not bytes(body)[:4] == b"PK\x03\x04"):
                return Response(400, {"detail": "Invalid DOCX file: File is not a zip file"})
            self.uploaded.append(name)
            return Response(200, {"status": "ok", "chunks_count": 2})

        if path == "/v1/chat/async":
            self._edits += 1
            self._polls = 0
            self._approved_at_poll = None
            ops = max(1, -(-self.sections_per_edit // 25))
            return Response(200, {"job_id": f"job-{self._edits}", "status": "pending",
                                  "usage": self._usage(ops)})

        if path.startswith("/v1/jobs/"):
            self._polls += 1
            if self._approved_at_poll is not None:
                # After approval the job resumes; it needs at least one more
                # poll before it is safe to export.
                if self._polls <= self._approved_at_poll + self.settle_polls:
                    return Response(200, {"status": "in_progress"})
                return Response(200, {"status": "completed"})
            if self._polls <= self.slow_polls:
                # Trap 2: a long quiet run. No usage block, still processing.
                return Response(200, {"status": "in_progress"})
            if self.envelope_pending:
                # The SSE `proposed_change_batch` shape: content is a JSON
                # *string* needing a second parse (Trap 1).
                pending = {"content": json.dumps({"changes": [
                    {"change_id": "ch_1", "chunk_id": "c1", "diff": "<p>after</p>"},
                ]})}
            else:
                # What GET /v1/jobs/{id} actually returns: a plain list.
                # Verified against the live API 2026-08-19.
                pending = [{"change_id": "ch_1", "chunk_id": "c1",
                            "old_html": "<p>before</p>", "new_html": "<p>after</p>"}]
            return Response(200, {
                "status": "awaiting_approval",
                "metadata": {"pending_changes": pending},
            })

        if path.endswith("/approve"):
            self.approved.extend(kw["json"]["changes"])
            # The real endpoint returns {"status": "ok"} and the job keeps
            # running; it reaches "completed" only on a later poll. Returning
            # "completed" here hid a race that silently exported the pre-edit
            # document. Verified live 2026-08-19.
            self._approved_at_poll = self._polls
            return Response(200, {"status": "ok", "usage": self._usage(0)})

        if path == "/v1/documents/export":
            import base64
            warn = base64.b64encode(json.dumps(
                [{"code": "field_code_unsupported", "detail": "a citation was skipped"}]
            ).encode()).decode()
            return Response(200, {"raw": b"DOCX"}, {"X-Export-Warnings": warn})

        return Response(404, {"error": "no such path"})
