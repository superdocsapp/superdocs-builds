"""Meter probe: measure what each call type actually costs.

Method, fixed before the result:

1. Reading the counter must itself be free, or no other number is trustworthy.
   The null probe reads it twice with nothing in between and requires a delta
   of 0. Everything after that is conditional on this passing.
2. One call per measurement window. Never batch. The delta between two
   consecutive reads is attributable to exactly one call.
3. Cheapest-risk-first ordering, so a wrong assumption is discovered having
   spent almost nothing.
4. Hard abort if cumulative spend exceeds the ceiling.

Nothing here is estimated. Every number written to the artefact is a measured
delta between two counter reads, or the probe records that it did not run.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from superdocs.client import SuperDocsError
from superdocs.mcp_transport import MCPHttpTransport

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CEILING = 20


class ProbeAborted(RuntimeError):
    pass


@dataclass
class Measurement:
    step: str
    tool: str
    cost: int | None
    used_before: int
    used_after: int
    ok: bool
    note: str = ""

    def as_dict(self) -> dict:
        return {"step": self.step, "tool": self.tool, "cost": self.cost,
                "used_before": self.used_before, "used_after": self.used_after,
                "ok": self.ok, "note": self.note}


@dataclass
class MeterProbe:
    transport: MCPHttpTransport
    ceiling: int = DEFAULT_CEILING
    measurements: list[Measurement] = field(default_factory=list)
    baseline: int = 0

    def used(self) -> int:
        status = self.transport.call("get_account_status", {})
        return int(status["quota"]["used"])

    def quota(self) -> dict:
        return self.transport.call("get_account_status", {})["quota"]

    def null_probe(self) -> bool:
        """Two reads, nothing between. Delta must be 0."""
        first, second = self.used(), self.used()
        delta = second - first
        self.measurements.append(Measurement(
            "null_probe", "get_account_status", delta, first, second,
            ok=(delta == 0),
            note="counter reads are free" if delta == 0
                 else "READING THE COUNTER IS BILLABLE; every later delta "
                      "needs this baseline subtracted"))
        self.baseline = first
        return delta == 0

    def measure(self, step: str, tool: str, params: dict,
                expect_error: bool = False):
        """One call, bracketed by two free counter reads."""
        before = self.used()
        if before - self.baseline > self.ceiling:
            raise ProbeAborted(
                f"spend {before - self.baseline} exceeds ceiling {self.ceiling}")
        result, ok, note = None, True, ""
        try:
            result = self.transport.call(tool, params)
            if isinstance(result, dict) and result.get("error"):
                ok, note = False, str(result["error"])[:200]
        except SuperDocsError as exc:
            ok, note = False, str(exc)[:200]
        after = self.used()
        if expect_error and ok:
            note = "expected an error but the call succeeded"
        self.measurements.append(Measurement(step, tool, after - before,
                                             before, after, ok, note))
        return result

    def total_spent(self) -> int:
        return (self.measurements[-1].used_after - self.baseline
                if self.measurements else 0)

    def confirmed_costs(self) -> dict[str, int]:
        """Tool -> measured cost. Only from successful, unambiguous windows."""
        costs: dict[str, int] = {}
        for m in self.measurements:
            if m.step in ("null_probe",) or m.cost is None or not m.ok:
                continue
            costs.setdefault(m.tool, m.cost)
        return costs

    def as_dict(self) -> dict:
        return {
            "method": "one call per window, bracketed by free counter reads",
            "ceiling": self.ceiling,
            "baseline_used": self.baseline,
            "total_spent": self.total_spent(),
            "measurements": [m.as_dict() for m in self.measurements],
            "confirmed_costs": self.confirmed_costs(),
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2) + "\n",
                        encoding="utf-8")


SAMPLE_DOC = b"<h1>Probe document</h1><p>A short fabricated memo for metering.</p>"


def run_probe(ceiling: int = DEFAULT_CEILING) -> MeterProbe:
    transport = MCPHttpTransport()
    transport.initialize()
    probe = MeterProbe(transport=transport, ceiling=ceiling)

    if not probe.null_probe():
        raise ProbeAborted("counter reads are billable; probe design invalid")

    # document_ids must be present even when empty: an empty argument object
    # is rejected with HTTP 422 (body required). Found by probing the shape
    # before spending, not by reading it off the brief.
    session = probe.measure("init_session", "init_session", {"document_ids": []})
    session_id = (session or {}).get("session_id")
    if not session_id:
        raise ProbeAborted(f"no session_id from init_session: {session}")

    probe.measure("upload", "upload_document_base64", {
        "filename": "probe.html",
        "file_base64": base64.b64encode(SAMPLE_DOC).decode("ascii"),
        "session_id": session_id})

    probe.measure("export", "export_document",
                  {"session_id": session_id, "format": "markdown"})
    probe.measure("download_url", "request_download_url",
                  {"session_id": session_id, "format": "docx"})

    chat = probe.measure("chat_memory_off", "chat", {
        "session_id": session_id,
        "message": "Change the heading to say Probe memo.",
        "cross_session_memory": False,
        "cross_session_search": False})
    job_id = _job_id_of(chat)

    if job_id:
        probe.measure("approve_single", "approve_change", {
            "session_id": session_id, "job_id": job_id, "approved": True})

    probe.measure("chat_search_on", "chat", {
        "session_id": session_id,
        "message": "Make the first sentence shorter.",
        "cross_session_memory": True,
        "cross_session_search": True,
        "cross_session_memory_key": "probe_scope",
        "cross_session_scope": ["probe_scope"]})

    probe.measure("clear_memory", "clear_cross_session_memory",
                  {"memory_key": "probe_scope"})

    probe.measure("errored_chat", "chat",
                  {"session_id": "not-a-real-session", "message": "hello"},
                  expect_error=True)
    return probe


def _job_id_of(chat_result) -> str | None:
    if not isinstance(chat_result, dict):
        return None
    for key in ("job_id", "jobId"):
        if chat_result.get(key):
            return chat_result[key]
    for key in ("job", "result", "data"):
        nested = chat_result.get(key)
        if isinstance(nested, dict) and nested.get("job_id"):
            return nested["job_id"]
    return None
