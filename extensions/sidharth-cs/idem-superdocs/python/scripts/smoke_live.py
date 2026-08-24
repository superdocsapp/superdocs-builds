#!/usr/bin/env python3
"""Optional live run against the real SuperDocs API. Spends metered operations.

Nothing in the test suite needs this. It exists to answer one question the
offline harness cannot: does the middleware behave the same way against the
real API, whose failures this library was written from?

Spend discipline, because the operations are billed:

  * every call that could be metered is counted before it is made
  * the counter hard-stops at IDEM_SMOKE_MAX_OPERATIONS and the run aborts
    rather than continuing past the cap
  * a request that errors is not billed for the edit it never made, so the
    422 wire probes in phase A are free and are counted separately
  * the actual spend is printed at the end and reported in the README

Run: make smoke
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from idem import (
    Idempotent,
    OutcomeUnknown,
    Policy,
    TerminalFailure,
    UnknownPolicy,
    Verdict,
)
from idem.superdocs import ApiError, SuperDocs

ROOT = Path(__file__).resolve().parents[2]
SESSION = f"idem-smoke-{int(time.time())}"


class CapExceeded(RuntimeError):
    pass


class Meter:
    """Counts metered calls and refuses to go past the cap.

    A successful write is billed; a request that errored is not. Both are
    tracked, because "we spent 11" is only a useful number next to "and 6
    attempts cost nothing".
    """

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.billed = 0
        self.free = 0

    def about_to_spend(self, what: str) -> None:
        if self.billed >= self.cap:
            raise CapExceeded(
                f"cap of {self.cap} metered operations reached before '{what}'. "
                f"Stopping rather than spending past it."
            )

    def billed_one(self, what: str) -> None:
        self.billed += 1
        print(f"    spent 1 ({self.billed}/{self.cap}) — {what}")

    def free_one(self, what: str) -> None:
        self.free += 1
        print(f"    free — {what}")


def load_key() -> str:
    """From the environment, or from a local .env. Never printed or logged."""
    key = os.environ.get("SUPERDOCS_API_KEY")
    if key:
        return key
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("SUPERDOCS_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    sys.exit("SUPERDOCS_API_KEY is not set. Copy .env.example to .env and fill it in.")


def check_tls(api: SuperDocs) -> None:
    """A missing CA bundle looks like a transport failure, which the table
    correctly calls never-sent and retryable — so the run spends its whole
    budget rediscovering it five times per phase. Check once, up front, and say
    what to do about it."""
    try:
        api.get_job("connectivity-probe-not-a-real-job")
    except ApiError as exc:
        if "SSLCertVerification" in str(exc) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
            sys.exit(
                "\nTLS verification failed: this Python has no CA bundle.\n"
                "  Fix:  SSL_CERT_FILE=/etc/ssl/cert.pem make smoke\n"
                "  (`make smoke` sets this for you when the system bundle exists;\n"
                "   running the script directly does not.)\n"
                "\nNothing was spent."
            )
        # Any other error means the transport works, which is all this checks.


def banner(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def phase_a_wire_shapes(api: SuperDocs, meter: Meter) -> None:
    """Free. Re-confirm the three places the live API and its documentation
    disagreed on 2026-08-21. A request that errors is not billed."""
    banner("A. wire shapes (free — these all error, so nothing is billed)")

    probes = [
        ("upload with the documented field name", "POST", "/v1/documents/upload-base64",
         {"document_base64": "e30=", "filename": "x.docx", "session_id": SESSION}),
        ("approve with the documented changes[] shape", "POST", f"/v1/chat/{SESSION}/approve",
         {"changes": [{"change_id": "nope", "approved": True}]}),
    ]
    for label, method, path, body in probes:
        try:
            api._call(method, path, body)
            print(f"    {label}: accepted (the documentation now matches the server)")
        except ApiError as exc:
            if exc.status is None:
                print(f"    {label}: no response ({exc}) — inconclusive, not a wire result")
            else:
                meter.free_one(f"{label} -> HTTP {exc.status}")


def phase_b_happy_path(api: SuperDocs, idem: Idempotent, meter: Meter) -> str | None:
    """The ordinary path through the middleware, and the replay that proves the
    key does its job against the real API."""
    banner("B. happy path through the middleware")

    document = b"<h1>Idempotency smoke</h1><p>The quick brown fox jumps over the lazy dog.</p>"
    meter.about_to_spend("upload")
    upload = idem.run(
        f"{SESSION}:upload",
        lambda: api.upload_base64(
            file_base64=base64.b64encode(document).decode(),
            filename="idem-smoke.html",
            session_id=SESSION,
        ),
    )
    meter.billed_one("upload")
    print(f"    uploaded: {str(upload)[:110]}")

    meter.about_to_spend("chat_async")
    job = idem.run(
        f"{SESSION}:edit-1",
        lambda: api.chat_async(
            message="Replace the word 'quick' with the word 'swift'. Change nothing else.",
            session_id=SESSION,
            approval_mode="auto",
        ),
    )
    meter.billed_one("chat_async")
    job_id = job.get("job_id") if isinstance(job, dict) else None
    print(f"    job: {job_id}")

    # The replay. Same key, no network call, no second edit, no second charge.
    replayed = idem.run(f"{SESSION}:edit-1", lambda: sys.exit("REPLAY EXECUTED — N1 VIOLATED"))
    print(f"    replayed the same key without spending: {replayed == job}")

    return job_id


def phase_c_partition(api: SuperDocs, idem: Idempotent, meter: Meter, job_id: str | None) -> None:
    """Force a real client-side timeout, then reconcile against the real
    GET /v1/jobs/{job_id}. This is the shape the whole library is about."""
    banner("C. partition and reconciliation against the live job state")

    if job_id is None:
        print("    no job id from phase B; skipping")
        return

    # A one-second ceiling on an operation that takes far longer. The server
    # keeps working; this client stops listening. Exactly the ambiguous failure.
    impatient = SuperDocs(api._key, api._base, timeout=1.0)

    meter.about_to_spend("chat_async (deliberately timed out)")
    key = f"{SESSION}:edit-2"
    try:
        idem.run(key, lambda: impatient.chat_async(
            message="Add one short closing sentence.", session_id=SESSION))
        print("    the call completed within 1s; no partition to reconcile")
        return
    except TerminalFailure as exc:
        # A session with a job still in flight rejects the next call outright —
        # the serialization constraint (item 10 in the bug report), not the
        # approve-never-settles wedge. The table calls 409 terminal either way,
        # so the library stops here instead of retrying into it.
        meter.free_one("chat_async -> 409, not billed")
        print(f"    the session returned 409 before the timeout could fire")
        print(f"    classified: {str(exc)[:90]}")
        print(f"    state: {idem.store.state_of(key)}, attempts: "
              f"{idem.store.get(key).attempts} (a retry loop would still be going)")
        return
    except OutcomeUnknown as exc:
        meter.billed_one("chat_async (timed out client-side; the server may have billed it)")
        print(f"    refused, as designed: {str(exc)[:100]}")

    print(f"    state is now: {idem.store.state_of(key)}")

    # The documented gap, live: this call timed out before returning a job id,
    # so there is nothing to ask the server about.
    print(f"    reconcile with no bound job id -> {idem.reconcile(key).value}")

    # And the reconciliation that does work: the phase-B job is real and its
    # state is readable, so a probe pointed at it resolves the unknown.
    verdict = idem.reconcile(key, probe=lambda _rec: api.job_settled_probe(job_id))
    print(f"    reconcile against the real job {job_id} -> {verdict.value}")


def phase_d_conflict(api: SuperDocs, idem: Idempotent, meter: Meter) -> None:
    """Show the table classifying a 409 terminal instead of looping.

    What this provokes is the serialization constraint: a second call against a
    session with a job still in flight. That is a documented constraint, not the
    approve-never-settles wedge, and the two should not be conflated — see
    README section 11.
    """
    banner("D. a session that will not accept work (409)")

    for n in range(6):
        if meter.billed >= meter.cap - 2:
            print("    stopping early to stay inside the cap")
            break
        key = f"{SESSION}:wedge-{n}"
        meter.about_to_spend(key)
        try:
            idem.run(key, lambda: api.chat_async(
                message=f"Append the digit {n} as a new paragraph.", session_id=SESSION))
            meter.billed_one(f"{key} succeeded")
        except TerminalFailure as exc:
            meter.free_one(f"{key} -> terminal, not retried: {str(exc)[:70]}")
            print("    409 classified terminal: zero retries, zero backoff.")
            print("    NB: this is the serialization 409 (a job still in flight on the")
            print("    session), not the approve-never-settles wedge. See README section 11.")
            return
        except OutcomeUnknown as exc:
            meter.billed_one(f"{key} -> unknown, refused: {str(exc)[:60]}")

    print("    no conflict provoked in this run")


def phase_e_review(api: SuperDocs, meter: Meter) -> None:
    """The Review surface, end to end, on its own fresh session.

    `approval_mode="ask_every_time"` stops the job at awaiting_approval, which
    makes the approval itself an operation worth protecting. Approving twice is
    as wrong as editing twice, and the wedge in the evidence came from exactly
    this call succeeding while the job never settled.
    """
    banner("E. the Review surface (approval_mode=ask_every_time)")

    review_session = f"{SESSION}-review"
    store = Path(os.environ.get("IDEM_SMOKE_REVIEW_STORE", "/tmp/idem-smoke-review.db"))
    store.unlink(missing_ok=True)
    idem = Idempotent(store, Policy.load(ROOT / "policy.json"),
                      job_probe=api.job_settled_probe)

    meter.about_to_spend("upload (review session)")
    document = b"<h1>Review smoke</h1><p>The comittee reviewed teh document quickly.</p>"
    idem.run(f"{review_session}:upload", lambda: api.upload_base64(
        file_base64=base64.b64encode(document).decode(),
        filename="idem-review.html", session_id=review_session))
    meter.billed_one("upload")

    meter.about_to_spend("chat_async ask_every_time")
    job = idem.run(f"{review_session}:propose", lambda: api.chat_async(
        message="Fix the spelling mistakes. Change nothing else.",
        session_id=review_session, approval_mode="ask_every_time"))
    meter.billed_one("chat_async (ask_every_time)")
    job_id = job.get("job_id")
    print(f"    job: {job_id}")

    # Polling is a free read. Wait for the Review gate to open.
    status, pending = None, None
    for _ in range(40):
        detail = api.get_job(job_id)
        status = detail.get("status")
        pending = (detail.get("metadata") or {}).get("pending_changes")
        if status in ("awaiting_approval", "completed", "failed", "cancelled"):
            break
        time.sleep(3)
    meter.free_one(f"polled to status={status} (reads are not billed)")
    print(f"    pending_changes: {type(pending).__name__} / "
          f"{len(pending) if isinstance(pending, list) else pending}")

    if status != "awaiting_approval":
        print(f"    the job settled as {status} without pausing for review.")
        print(f"    that is bug 1 from the report: ask_every_time was bypassed.")
        return

    change_ids = [c.get("change_id") for c in pending] if isinstance(pending, list) else None
    print(f"    change ids: {change_ids}")

    # The approval, through the middleware.
    key = f"{review_session}:approve"
    meter.about_to_spend("approve")
    decision = idem.run(key, lambda: api.approve(
        session_id=review_session, job_id=job_id, approved=True,
        changes=[{"change_id": c, "approved": True} for c in change_ids] if change_ids else None))
    meter.billed_one("approve")
    print(f"    approve returned: {decision}")

    # The replay. Same key, no second approval, no second charge.
    replay = idem.run(key, lambda: sys.exit("RE-APPROVED — the Review surface double-applied"))
    print(f"    replayed the approval without spending: {replay == decision}")

    # Did the job actually settle? The evidence says this is where it wedges.
    settled = None
    for _ in range(20):
        settled = api.get_job(job_id).get("status")
        if settled in ("completed", "failed", "cancelled"):
            break
        time.sleep(3)
    meter.free_one(f"post-approval poll -> {settled}")
    probe = api.job_settled_probe(job_id)
    verdict = probe[0].value if isinstance(probe, tuple) else probe.value
    print(f"    job after approval: {settled}")
    print(f"    job_settled_probe: {verdict}")

    if settled not in ("completed", "failed", "cancelled"):
        print("    the approval succeeded and the job never settled — bug 5, live.")
        print("    the probe answers INCONCLUSIVE rather than claiming success.")


def main() -> None:
    cap = int(os.environ.get("IDEM_SMOKE_MAX_OPERATIONS", "25"))
    meter = Meter(cap)
    api = SuperDocs(load_key())
    store = Path(os.environ.get("IDEM_SMOKE_STORE", "/tmp/idem-smoke.db"))
    store.unlink(missing_ok=True)
    idem = Idempotent(store, Policy.load(ROOT / "policy.json"),
                      job_probe=api.job_settled_probe)

    print(f"session: {SESSION}")
    print(f"cap:     {cap} metered operations (hard stop)")
    check_tls(api)

    job_id = None
    # Re-running a phase re-spends it, so phases can be selected:
    #   IDEM_SMOKE_PHASES=E make smoke
    wanted = set(os.environ.get("IDEM_SMOKE_PHASES", "ABCDE").upper())

    for name, phase in [
        ("A", lambda: phase_a_wire_shapes(api, meter)),
        ("B", lambda: phase_b_happy_path(api, idem, meter)),
        ("C", lambda: phase_c_partition(api, idem, meter, job_id)),
        ("D", lambda: phase_d_conflict(api, idem, meter)),
        ("E", lambda: phase_e_review(api, meter)),
    ]:
        if name not in wanted:
            continue
        try:
            outcome = phase()
            if name == "B":
                job_id = outcome
        except CapExceeded as exc:
            print(f"\n    STOPPED: {exc}")
            break
        except ApiError as exc:
            print(f"\n    phase {name} ended on HTTP {exc.status}: {exc}")
        except Exception as exc:
            # A surprise in one phase must not cost the spend report.
            print(f"\n    phase {name} raised {type(exc).__name__}: {str(exc)[:150]}")

    banner("spend")
    print(f"    metered operations: {meter.billed} (cap {cap})")
    print(f"    free calls (errored or read-only): {meter.free}")
    print(f"    store: {store}")


if __name__ == "__main__":
    main()
