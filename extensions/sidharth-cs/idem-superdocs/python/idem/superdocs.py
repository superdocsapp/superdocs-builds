"""A thin SuperDocs client that raises errors the decision table can read.

Optional: the core library never imports this, and the whole test suite runs
without it. It exists because the interesting half of "make retries safe" is
deciding, for a real failure from a real API, whether the request was sent —
and that judgement belongs in the transport adapter, not in the policy.

stdlib urllib rather than httpx or requests, so the package has zero runtime
dependencies. The cost is stated in `_shape` below.

Wire shapes verified against the live API on 2026-08-21, where the published
documentation and the server disagree:

  * upload takes `file_base64`, not the documented `document_base64`
  * approve takes {job_id, approved}; the documented {changes: [...]} shape 422s
  * metadata.pending_changes is null, not [], when nothing has changed
"""

from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request

from idem.runner import Verdict

TERMINAL_JOB_STATES = ("completed", "failed", "cancelled")


class ApiError(Exception):
    """Carries the two things the table matches on: the status, and whether the
    request left the client."""

    def __init__(self, message: str, *, status: int | None, sent: bool,
                 retry_after_ms: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.sent = sent
        self.retry_after_ms = retry_after_ms


def _shape(exc: Exception) -> ApiError:
    """Turn a urllib failure into something the table can classify.

    The `sent` judgement, case by case:

      * an HTTP status means the server answered, so it was certainly sent
      * a refused connection, a DNS failure, or a failed TLS handshake means no
        request was ever written, so it certainly was not. The TLS case was
        added after a live run: the handshake failed on a certificate error and
        the adapter reported it as sent, so the library refused an operation
        that provably could not have happened. Correct in the safe direction,
        and still wrong.
      * a timeout is the hard one. urllib uses a single timeout covering both
        the connect and the read, so it cannot say which one elapsed. This
        adapter reports sent=True, which is the fail-closed answer: the cost of
        being wrong is a refused retry the caller can reconcile, where the
        other way round the cost is a duplicate metered edit.

    ponytail: httpx distinguishes ConnectTimeout from ReadTimeout natively and
    the table already has a rule for each. Swap the transport if the refused
    retries on connect timeouts ever become a real cost; the policy needs no
    change, which is the point of keeping it in data.
    """
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        return ApiError(
            f"HTTP {exc.code}: {exc.reason}",
            status=exc.code,
            sent=True,
            retry_after_ms=float(retry_after) * 1000 if retry_after and retry_after.isdigit() else None,
        )
    if isinstance(exc, urllib.error.URLError):
        never_sent = isinstance(
            exc.reason, (ConnectionRefusedError, socket.gaierror, ssl.SSLError)
        )
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            never_sent = False
        return ApiError(f"{type(exc.reason).__name__}: {exc.reason}",
                        status=None, sent=not never_sent)
    return ApiError(f"{type(exc).__name__}: {exc}", status=None, sent=True)


class SuperDocs:
    def __init__(self, api_key: str, base_url: str = "https://api.superdocs.app",
                 timeout: float = 180.0) -> None:
        # Document operations run 30s to several minutes. A real ceiling still
        # exists so nothing waits forever.
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            f"{self._base}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except Exception as exc:
            raise _shape(exc) from exc

    # ---- the endpoints this build touches -----------------------------------

    def upload_base64(self, *, file_base64: str, filename: str, session_id: str) -> dict:
        return self._call("POST", "/v1/documents/upload-base64", {
            "file_base64": file_base64, "filename": filename,
            "session_id": session_id, "return_html": True,
        })

    def chat_async(self, *, message: str, session_id: str, approval_mode: str = "auto") -> dict:
        return self._call("POST", "/v1/chat/async", {
            "message": message, "session_id": session_id, "approval_mode": approval_mode,
        })

    def get_job(self, job_id: str) -> dict:
        return self._call("GET", f"/v1/jobs/{job_id}")

    def approve(self, *, session_id: str, job_id: str, approved: bool,
                changes: list[dict] | None = None) -> dict:
        """Decide proposed changes. `{job_id, approved}` are the two fields the
        live API's own 422 names as required; `changes` is sent only when the
        caller has change ids, because the documented changes-only shape 422s."""
        body: dict[str, object] = {"job_id": job_id, "approved": approved}
        if changes is not None:
            body["changes"] = changes
        return self._call("POST", f"/v1/chat/{session_id}/approve", body)

    def revert_session(self, *, session_id: str, turn_index: int) -> dict:
        return self._call("POST", f"/v1/sessions/{session_id}/revert",
                          {"turn_index": turn_index})

    def get_document(self, document_id: str) -> dict:
        """Structure read: headings, section_count, block_count. Free — never
        billed — which makes it the honest way to count applied edits when the
        content itself varies run to run."""
        return self._call("GET", f"/v1/documents/{document_id}")

    # ---- reconciliation probes ----------------------------------------------
    #
    # Two, not one, because "was it applied" means different things for
    # different operations and a single probe would have to guess which.

    def job_exists_probe(self, job_id: str) -> Verdict | tuple[Verdict, object]:
        """For create-shaped operations such as chat_async, where the operation
        IS the creation of the job. If the job exists, the call landed."""
        try:
            return (Verdict.APPLIED, self.get_job(job_id))
        except ApiError as exc:
            if exc.status == 404:
                return Verdict.NOT_APPLIED
            return Verdict.INCONCLUSIVE

    def job_settled_probe(self, job_id: str) -> Verdict | tuple[Verdict, object]:
        """For settle-shaped operations such as approve, where the operation is
        only complete once the job reaches a terminal state.

        A job still running returns INCONCLUSIVE rather than APPLIED. That is
        the exact case behind the wedge in the evidence: an approve that
        returned success while the job never settled. Calling that applied
        would be the library inventing the outcome it was built to refuse."""
        try:
            job = self.get_job(job_id)
        except ApiError as exc:
            return Verdict.NOT_APPLIED if exc.status == 404 else Verdict.INCONCLUSIVE
        if job.get("status") in TERMINAL_JOB_STATES:
            return (Verdict.APPLIED, job)
        return Verdict.INCONCLUSIVE
