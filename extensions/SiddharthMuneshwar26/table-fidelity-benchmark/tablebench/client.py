"""The four calls: upload, chat, approve, export.

The API key is read from the SUPERDOCS_API_KEY environment variable and is
never accepted as an argument, never logged, and never written to a result
file. Nothing in this repository should ever hold a credential.

FakeClient is the offline counterpart. It is not here to make tests pass --
it is here so the comparator can be tested against faults whose ground truth
is known: flatten a merge, drop a colspan, strip a trailing zero, then assert
the comparator reports exactly that and nothing else.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

BASE = os.environ.get("SUPERDOCS_BASE", "https://api.superdocs.app")

# One chat turn is one operation. Uploads, exports and downloads are free per
# the published pricing; if that changes, change it here and nowhere else.
OP_COST = {"upload": 0, "chat": 1, "approve": 0, "export": 0}


class ApiError(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Ledger:
    """Operation accounting with a hard cap checked before every spend."""

    cap: int
    spent: int = 0
    by_stage: dict[str, int] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)

    def charge(self, stage: str) -> None:
        cost = OP_COST.get(stage, 0)
        if cost and self.spent + cost > self.cap:
            raise BudgetExceeded(
                f"stage {stage!r} would spend {cost} op, taking the run to "
                f"{self.spent + cost} against a cap of {self.cap}. Stopping "
                f"before the spend, not after."
            )
        self.spent += cost
        self.by_stage[stage] = self.by_stage.get(stage, 0) + cost

    def record_time(self, stage: str, seconds: float) -> None:
        self.timings[stage] = self.timings.get(stage, 0.0) + seconds


class SuperDocsClient:
    """Live client. Requires SUPERDOCS_API_KEY in the environment."""

    def __init__(self, ledger: Ledger, poll_interval: float = 3.0,
                 timeout_s: float = 600.0):
        key = os.environ.get("SUPERDOCS_API_KEY")
        if not key:
            raise ApiError(
                "SUPERDOCS_API_KEY is not set. Export it in your shell "
                "(and keep it out of shell history with a leading space); "
                "the benchmark never takes a key as an argument."
            )
        self._key = key
        self.ledger = ledger
        self.poll_interval = poll_interval
        self.timeout_s = timeout_s

    # -- internals ---------------------------------------------------------
    @property
    def _json_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json"}

    @property
    def _auth_only(self) -> dict:
        return {"Authorization": f"Bearer {self._key}"}

    def _redact(self, text: str) -> str:
        return re.sub(r"sk_[A-Za-z0-9_\-]{4,}", "sk_[REDACTED]", text or "")

    def _check(self, resp, what: str):
        if resp.status_code >= 400:
            raise ApiError(
                f"{what} failed with HTTP {resp.status_code}: "
                f"{self._redact(resp.text)[:400]}"
            )
        return resp

    # -- the four calls ----------------------------------------------------
    def upload(self, path: str, session_id: str) -> str:
        import requests
        t0 = time.monotonic()
        self.ledger.charge("upload")
        with open(path, "rb") as fh:
            r = requests.post(
                f"{BASE}/v1/documents/upload",
                headers=self._auth_only,
                files={"file": (os.path.basename(path), fh,
                                "application/vnd.openxmlformats-officedocument."
                                "wordprocessingml.document")},
                data={"session_id": session_id},
                timeout=self.timeout_s,
            )
        self._check(r, "upload")
        self.ledger.record_time("upload", time.monotonic() - t0)
        html = r.json().get("html")
        if not html:
            raise ApiError("upload returned no html; cannot proceed honestly")
        return html

    def edit(self, session_id: str, document_html: str, instruction: str) -> dict:
        """Start an approval-gated edit and poll to the approval point."""
        import requests
        t0 = time.monotonic()
        self.ledger.charge("chat")
        r = requests.post(
            f"{BASE}/v1/chat/async", headers=self._json_headers,
            json={
                "message": instruction,
                "session_id": session_id,
                "document_html": document_html,
                "approval_mode": "ask_every_time",
            },
            timeout=self.timeout_s,
        )
        self._check(r, "chat/async")
        job_id = r.json()["job_id"]

        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            j = requests.get(f"{BASE}/v1/jobs/{job_id}",
                             headers=self._json_headers,
                             timeout=self.timeout_s)
            self._check(j, "jobs/get")
            job = j.json()
            status = job.get("status")
            if status == "awaiting_approval":
                self.ledger.record_time("chat", time.monotonic() - t0)
                return {"job_id": job_id,
                        "pending": self._pending(job),
                        "status": status}
            if status == "completed":
                self.ledger.record_time("chat", time.monotonic() - t0)
                return {"job_id": job_id, "pending": [], "status": status,
                        "result": job.get("result")}
            if status in ("failed", "cancelled"):
                raise ApiError(
                    f"job {status}: {self._redact(str(job.get('error')))[:300]}"
                )
            time.sleep(self.poll_interval)
        raise ApiError(
            f"job {job_id} did not reach a terminal state within "
            f"{self.timeout_s:.0f}s. Long silence is normal on this API, so "
            f"this is a timeout, not a proven failure."
        )

    @staticmethod
    def _pending(job: dict) -> list[dict]:
        """Proposed changes need a second parse.

        The documented gotcha: proposed-change content arrives as a
        JSON-encoded string while the final result is already an object.
        Missing this is what makes every diff field read as undefined.
        """
        changes = (job.get("metadata") or {}).get("pending_changes") or []
        out = []
        for c in changes:
            c = dict(c)
            content = c.get("content")
            if isinstance(content, str):
                try:
                    c["content"] = json.loads(content)
                except (ValueError, TypeError):
                    c["content_parse_failed"] = True
            out.append(c)
        return out

    def approve(self, session_id: str, job_id: str, changes: list[dict]) -> dict:
        import requests
        t0 = time.monotonic()
        self.ledger.charge("approve")
        r = requests.post(
            f"{BASE}/v1/chat/{session_id}/approve",
            headers=self._json_headers,
            json={
                "job_id": job_id,
                "approved": True,
                "changes": [{"change_id": c.get("change_id"), "approved": True}
                            for c in changes],
            },
            timeout=self.timeout_s,
        )
        self._check(r, "approve")
        self.ledger.record_time("approve", time.monotonic() - t0)
        return r.json()

    def export(self, session_id: str, out_path: str) -> str:
        import requests
        t0 = time.monotonic()
        self.ledger.charge("export")
        r = requests.post(
            f"{BASE}/v1/documents/export", headers=self._json_headers,
            json={"session_id": session_id, "format": "docx"},
            timeout=self.timeout_s,
        )
        self._check(r, "export")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(r.content)
        self.ledger.record_time("export", time.monotonic() - t0)
        return out_path


# --------------------------------------------------------------------------
# Offline fake
# --------------------------------------------------------------------------

FAULTS = (
    "none",
    "flatten_merges",      # drop rowspan/colspan attributes
    "drop_nested",         # remove nested tables
    "strip_trailing_zero", # 12.480 -> 12.48
    "drop_shading",        # remove background colours
    "rewrite_body",        # touch a paragraph nobody asked about
)


class FakeClient:
    """Deterministic offline stand-in with injectable, named faults."""

    def __init__(self, ledger: Ledger, fault: str = "none"):
        if fault not in FAULTS:
            raise ValueError(f"unknown fault {fault!r}; known: {FAULTS}")
        self.ledger = ledger
        self.fault = fault
        self._sessions: dict[str, str] = {}
        self._sim: dict[str, tuple] = {}

    def simulate_edit(self, session_id: str, case) -> None:
        """Simulator affordance, offline only.

        Records the change the live model would be asked to make, so the dry
        run exercises the real success path instead of asserting failure on
        every case. The live client has no such method and the runner only
        calls it when the client offers one.
        """
        if case.expect_contains is not None:
            self._sim[session_id] = (case.target, case.expect_contains)

    def upload(self, path: str, session_id: str) -> str:
        from .extract import from_docx
        from .htmlout import to_html
        self.ledger.charge("upload")
        html = to_html(from_docx(path))
        self._sessions[session_id] = html
        return html

    def edit(self, session_id: str, document_html: str, instruction: str) -> dict:
        self.ledger.charge("chat")
        self._sessions[session_id] = document_html
        return {"job_id": f"fake-{session_id}", "status": "awaiting_approval",
                "pending": [{"change_id": "c1", "operation": "replace",
                             "content": json.dumps({"instruction": instruction})}]}

    def approve(self, session_id: str, job_id: str, changes: list[dict]) -> dict:
        self.ledger.charge("approve")
        return {"status": "applied", "applied": len(changes)}

    def export(self, session_id: str, out_path: str) -> str:
        from .extract import from_html
        from .corpus.generate import write_docx
        from .htmlout import doc_to_case
        self.ledger.charge("export")
        doc = from_html(self._damage(self._sessions.get(session_id, "")))
        sim = self._sim.get(session_id)
        if sim:
            (ti, r, c), text = sim
            if ti < len(doc.tables):
                cell = doc.tables[ti].cell_at(r, c)
                if cell is not None:
                    if cell.nested:
                        cell.nested[0].cells[-1].paragraphs = [text]
                    else:
                        cell.paragraphs = [text]
        write_docx(doc_to_case(doc), out_path)
        return out_path

    def _damage(self, html: str) -> str:
        f = self.fault
        if f == "none":
            return html
        if f == "flatten_merges":
            return re.sub(r'\s(rowspan|colspan)="\d+"', "", html)
        if f == "drop_nested":
            return re.sub(r"<table\b[^>]*>(?:(?!</table>).)*?</table>\s*(?=</td>)",
                          "", html, flags=re.S)
        if f == "strip_trailing_zero":
            return re.sub(r"(\d+\.\d*?)0+(?=\D|$)", r"\1", html)
        if f == "drop_shading":
            return re.sub(r"background-color:[^;\"]*;?", "", html)
        if f == "rewrite_body":
            return html.replace("Prepared for benchmark purposes.",
                                "Prepared automatically.")
        return html
