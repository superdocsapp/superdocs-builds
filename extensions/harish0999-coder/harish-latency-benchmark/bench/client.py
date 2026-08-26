"""
Thin, phase-timed client for the SuperDocs REST API.

Maps directly onto the assigned build's required phase breakdown
(upload / processing / editing / export):

  upload      -> POST /v1/documents/upload
  processing  -> POST /v1/chat/async (approval_mode="ask_every_time"),
                 polling GET /v1/jobs/{job_id} until status="awaiting_approval"
  editing     -> POST /v1/chat/{session_id}/approve, then polling
                 GET /v1/jobs/{job_id} until status="completed"
  export      -> POST /v1/documents/export

Every call returns a PhaseResult carrying wall-clock latency, whether the
response was a 429 (rate limit -- excluded from latency stats, see stats.py),
and the parsed body. Nothing here retries automatically: retry policy is the
runner's job (small-sample mode, backoff), not the client's.

Network-level exceptions (timeouts, TLS handshake failures, connection
resets) are caught and converted into an errored PhaseResult rather than
propagating -- confirmed necessary during a real --full run, where a single
transient ConnectTimeout on cycle 25/60 crashed the whole process and lost
every result collected so far (bench_report.json is only written after
run_benchmark() returns cleanly). See README's "What broke" section.
"""
from __future__ import annotations

import time
import dataclasses
from typing import Any, Optional

import httpx

BASE_URL = "https://api.superdocs.app"


@dataclasses.dataclass
class PhaseResult:
    phase: str
    latency_s: float
    status_code: int
    rate_limited: bool
    ops_charged: Optional[int]
    body: Any
    error: Optional[str] = None


class SuperDocsClient:
    def __init__(self, api_key: str, timeout_s: float = 60.0):
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.Client(base_url=BASE_URL, headers=self._headers, timeout=timeout_s)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _safe_call(self, phase: str, request_fn, t0: float, is_binary: bool = False) -> PhaseResult:
        """
        Runs one httpx call, converting network-level exceptions (timeouts,
        connection resets, TLS handshake failures -- all real, all observed
        during a live run of this tool) into an errored PhaseResult instead
        of letting them propagate and crash the whole benchmark. A single
        transient network blip on request N of 60 should not lose the
        telemetry already collected from requests 1..N-1.
        """
        try:
            r = request_fn()
        except httpx.HTTPError as e:
            return self._wrap(phase, t0, None, error=f"{type(e).__name__}: {e}")
        return self._wrap(phase, t0, r, is_binary=is_binary)

    # -- account / cheap verification (does not consume operations) --------
    def whoami_sessions(self) -> PhaseResult:
        t0 = time.perf_counter()
        return self._safe_call("verify_key", lambda: self._client.get("/v1/sessions"), t0)

    # -- phase 1: upload -----------------------------------------------------
    def upload_document(self, filename: str, content: bytes, session_id: str) -> PhaseResult:
        t0 = time.perf_counter()
        files = {"file": (filename, content, "text/plain")}
        data = {"session_id": session_id}
        return self._safe_call("upload",
                                lambda: self._client.post("/v1/documents/upload", files=files, data=data),
                                t0)

    # -- phase 2: processing (submit + poll to awaiting_approval) -----------
    def submit_edit_async(self, session_id: str, message: str,
                           approval_mode: str = "ask_every_time") -> PhaseResult:
        t0 = time.perf_counter()
        body = {"message": message, "session_id": session_id, "approval_mode": approval_mode}
        return self._safe_call("processing_submit",
                                lambda: self._client.post("/v1/chat/async", json=body), t0)

    def poll_job(self, job_id: str, until_status: set[str], poll_interval_s: float = 0.5,
                 timeout_s: float = 120.0, phase_label: str = "processing_poll") -> PhaseResult:
        t0 = time.perf_counter()
        deadline = time.perf_counter() + timeout_s
        last_r = None
        last_exc = None
        while time.perf_counter() < deadline:
            try:
                r = self._client.get(f"/v1/jobs/{job_id}")
            except httpx.HTTPError as e:
                # Transient network error mid-poll: don't fail the whole
                # phase on one bad GET -- retry until the deadline, same as
                # a slow-but-alive server would be handled.
                last_exc = e
                time.sleep(poll_interval_s)
                continue
            last_r = r
            last_exc = None
            if r.status_code == 429:
                return self._wrap(phase_label, t0, r)
            if r.status_code == 200:
                status = r.json().get("status")
                if status in until_status:
                    return self._wrap(phase_label, t0, r)
                if status in ("failed", "cancelled"):
                    return self._wrap(phase_label, t0, r, error=f"job ended in {status}")
            time.sleep(poll_interval_s)
        if last_r is None and last_exc is not None:
            return self._wrap(phase_label, t0, None,
                               error=f"poll timeout (last error: {type(last_exc).__name__}: {last_exc})")
        return self._wrap(phase_label, t0, last_r, error="poll timeout")

    # -- phase 3: editing (approve + poll to completed) ----------------------
    def approve_all(self, session_id: str, job_id: str, pending_changes: list[dict]) -> PhaseResult:
        # Confirmed against the live API (not assumed from docs): job_id +
        # approved alone returns HTTP 200 with batch_complete=false and the
        # job silently never leaves awaiting_approval. Including change_id
        # (from the specific pending_changes[] entry) is what actually
        # closes the batch -- see README's "What broke" section for the
        # empirical trail. This benchmark only ever proposes one change per
        # cycle, so pending_changes[0] is always the right one here.
        t0 = time.perf_counter()
        change_id = pending_changes[0].get("change_id") if pending_changes else None
        payload = {"job_id": job_id, "approved": True}
        if change_id:
            payload["change_id"] = change_id
        return self._safe_call("editing_approve",
                                lambda: self._client.post(f"/v1/chat/{session_id}/approve", json=payload),
                                t0)

    # -- phase 4: export -------------------------------------------------------
    def export_document(self, session_id: str, fmt: str = "docx") -> PhaseResult:
        t0 = time.perf_counter()
        return self._safe_call("export",
                                lambda: self._client.post("/v1/documents/export",
                                                           json={"session_id": session_id, "format": fmt}),
                                t0, is_binary=True)

    # -- shared response handling ----------------------------------------------
    def _wrap(self, phase: str, t0: float, r: Optional[httpx.Response],
              error: Optional[str] = None, is_binary: bool = False) -> PhaseResult:
        latency = time.perf_counter() - t0
        if r is None:
            return PhaseResult(phase, latency, 0, False, None, None, error=error or "no response")
        rate_limited = r.status_code == 429
        ops_charged = None
        body: Any = None
        if not is_binary:
            try:
                body = r.json()
                usage = body.get("usage") if isinstance(body, dict) else None
                if usage:
                    ops_charged = usage.get("ops_charged")
            except Exception:
                body = None
        return PhaseResult(phase, latency, r.status_code, rate_limited, ops_charged, body, error=error)
