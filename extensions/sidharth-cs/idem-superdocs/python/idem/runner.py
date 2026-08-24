"""The middleware: claim a key, attempt the operation, classify what happened,
and refuse to guess.

This module branches on the four abstract outcomes the table can return —
success, retryable, terminal, unknown — and on nothing else. There is no HTTP
status code and no error class name anywhere in this file; putting one here is
what the build exists to argue against, and a test greps for it (SPEC.md R7).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from idem.policy import Policy
from idem.store import FAILED, IN_FLIGHT, SUCCEEDED, UNKNOWN, Record, Store

log = logging.getLogger("idem")

SUCCESS = "success"
RETRYABLE = "retryable"
TERMINAL = "terminal"
UNKNOWN_OUTCOME = "unknown"


class UnknownPolicy(Enum):
    """What to do when an attempt's outcome cannot be determined. There is no
    safe default, so the default is to stop and let a human decide."""

    REFUSE = "refuse"
    RECONCILE = "reconcile"
    RETRY_ANYWAY = "retry_anyway"


class Verdict(Enum):
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    INCONCLUSIVE = "inconclusive"


class OutcomeUnknown(RuntimeError):
    """The outcome is unknown and nothing authorised a retry. The operation may
    or may not have been applied; this exception is the library declining to
    guess which."""


class TerminalFailure(RuntimeError):
    """The table classified the failure terminal. Retrying will not help."""


class RetriesExhausted(RuntimeError):
    """The retry budget ran out on a failure that provably never reached the
    server. The key has been released; a later caller starts genuinely fresh."""


def _observe(exc: BaseException) -> tuple[int | None, str, bool, float | None]:
    """Reduce a raised exception to the four things the table can match on.

    Attribute lookups only. This never imports an HTTP library, and never
    compares a status to a literal — it just reports what it found.
    """
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    # Absent an explicit attestation, assume the request WAS sent. Assuming
    # otherwise is precisely how a retry library double-applies.
    sent = bool(getattr(exc, "sent", True))
    retry_after_ms = getattr(exc, "retry_after_ms", None)
    return status, type(exc).__name__, sent, retry_after_ms


def _default_job_id(result: object) -> str | None:
    return result.get("job_id") if isinstance(result, dict) else None


class Idempotent:
    def __init__(
        self,
        store_path: str | Path,
        policy: Policy,
        *,
        job_probe: Callable[[str], Verdict | tuple[Verdict, object]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        extract_job_id: Callable[[object], str | None] = _default_job_id,
    ) -> None:
        self.store = Store(store_path)
        self.policy = policy
        self._job_probe = job_probe
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._extract_job_id = extract_job_id

    # ---- public surface -----------------------------------------------------

    def run(
        self,
        key: str,
        fn: Callable[[], object],
        *,
        on_unknown: UnknownPolicy = UnknownPolicy.REFUSE,
        probe: Callable[[Record], Verdict | tuple[Verdict, object]] | None = None,
        naturally_idempotent: bool = False,
    ) -> object:
        existing = self.store.claim(key)
        if existing is None:
            return self._attempt_loop(key, fn, on_unknown, probe, naturally_idempotent)

        if existing.state == SUCCEEDED:
            return existing.result  # R3 / N1: never execute a completed key
        if existing.state == FAILED:
            raise TerminalFailure(existing.detail or "operation previously failed terminally")
        if existing.state == IN_FLIGHT:
            if existing.owned_by_this_process:
                raise OutcomeUnknown(
                    f"key {key!r} is held by another caller in this process"
                )
            # The owning process is gone, or is another live process. Both are
            # unsafe to execute and neither is distinguishable from here, so
            # fail closed: this becomes an unknown outcome (N4).
            self.store.mark_unknown(
                key, f"in-flight record left by pid {existing.owner_pid}"
            )

        return self._resolve_unknown(key, fn, on_unknown, probe, naturally_idempotent)

    def reconcile(
        self,
        key: str,
        probe: Callable[[Record], Verdict | tuple[Verdict, object]] | None = None,
    ) -> Verdict:
        """Ask what actually happened. Public and callable on its own (R13).

        Returns APPLIED (record becomes succeeded, the function is never
        re-run), NOT_APPLIED (the key is released and may be retried), or
        INCONCLUSIVE (the record stays unknown and stays refused).
        """
        rec = self.store.get(key)
        if rec is None:
            return Verdict.INCONCLUSIVE
        if rec.state == SUCCEEDED:
            return Verdict.APPLIED

        answer = self._ask(rec, probe)
        verdict, result = answer if isinstance(answer, tuple) else (answer, None)

        if verdict is Verdict.APPLIED:
            self.store.succeed(key, result if result is not None else rec.result)
        elif verdict is Verdict.NOT_APPLIED:
            # Same invariant as a retryable outcome: provably not applied, so
            # releasing the key cannot cause a double-apply (R10).
            self.store.release(key)
        return verdict

    # ---- internals ----------------------------------------------------------

    def _ask(self, rec: Record, probe) -> Verdict | tuple[Verdict, object]:
        if probe is not None:
            return probe(rec)
        # The documented limit (SPEC.md 6): with no job id bound and no job
        # probe configured, there is nothing to ask, and "I could not find
        # out" must never be mistaken for "it did not happen".
        if self._job_probe is None or rec.job_id is None:
            return Verdict.INCONCLUSIVE
        return self._job_probe(rec.job_id)

    def _resolve_unknown(self, key, fn, on_unknown, probe, naturally_idempotent, spent=0):
        """An unknown outcome is never retried without an explicit policy
        choice (R12). This is the only place that choice is honoured."""
        rec = self.store.get(key)
        detail = (rec.detail if rec else None) or "outcome unknown"

        if on_unknown is UnknownPolicy.REFUSE:
            raise OutcomeUnknown(
                f"{detail}; the operation may or may not have been applied. "
                f"Reconcile it, or choose a policy explicitly."
            )

        if on_unknown is UnknownPolicy.RECONCILE:
            verdict = self.reconcile(key, probe)
            if verdict is Verdict.APPLIED:
                return self.store.get(key).result
            if verdict is Verdict.INCONCLUSIVE:
                raise OutcomeUnknown(f"{detail}; reconciliation was inconclusive")

        elif on_unknown is UnknownPolicy.RETRY_ANYWAY:
            if not naturally_idempotent:
                raise OutcomeUnknown(
                    "UnknownPolicy.RETRY_ANYWAY also requires naturally_idempotent=True. "
                    "Retrying an unknown outcome is only sound when repeating the "
                    "operation cannot change the result, and only the caller knows that."
                )
            log.warning(
                "retrying key %r after an unknown outcome (%s) because the caller "
                "asserted the operation is naturally idempotent",
                key, detail,
            )
            self.store.release(key)

        # Reconciliation said not-applied, or the caller vouched for the
        # operation. Either way the key is released and a fresh attempt is now
        # justified rather than assumed.
        self.store.claim(key)
        # The delay belongs to the attempt that just failed, not the next
        # one, so back off by one from the running count.
        self._pause(max(0, spent - 1), None)
        return self._attempt_loop(key, fn, on_unknown, probe, naturally_idempotent, spent)

    def _attempt_loop(self, key, fn, on_unknown, probe, naturally_idempotent, spent=0):
        """`spent` is the number of attempts this run() has already made,
        including those made before an unknown outcome was resolved.

        It has to be threaded through rather than recomputed from the record,
        because resolving an unknown releases the key and that resets the
        record's own count. Without it, every reconcile-says-not-applied starts
        a fresh budget and run() can loop forever — which is the exact
        unbounded retry this library exists to prevent. Found by the fuzzer
        (`test_fuzz.py`), not by design.
        """
        budget = self.policy.backoff.max_attempts
        for attempt in range(spent, budget):
            self.store.record_attempt(key)
            try:
                result = fn()
            except Exception as exc:
                # Exception, not BaseException: KeyboardInterrupt and SystemExit
                # must propagate. They leave an in-flight record behind, which
                # is correct — a record abandoned by a dying process is exactly
                # the unknown outcome N4 exists to catch.
                #
                # Everything else, including a plain bug in fn(), goes to the
                # table. From here a TypeError raised before the request and one
                # raised while reading the response are indistinguishable, so
                # the catch-all classifies it unknown and the library refuses.
                # Fail closed (R8).
                status, error, sent, retry_after_ms = _observe(exc)
                rule = self.policy.classify(status=status, error=error, sent=sent)

                if rule.outcome == RETRYABLE:
                    if attempt == budget - 1:
                        self.store.release(key)
                        raise RetriesExhausted(
                            f"{budget} attempts on key {key!r}, last: {rule.id} ({exc!r})"
                        ) from exc
                    self._pause(attempt, retry_after_ms if rule.honour_retry_after else None)
                    continue

                if rule.outcome == TERMINAL:
                    self.store.fail(key, f"{rule.id}: {exc!r}")
                    raise TerminalFailure(f"{rule.id}: {rule.why}") from exc

                self.store.mark_unknown(key, f"{rule.id}: {exc!r}")
                if attempt == budget - 1:
                    # The budget is spent. An unknown outcome stays unknown
                    # rather than silently becoming another attempt.
                    raise OutcomeUnknown(
                        f"{rule.id}: {exc!r}; the retry budget is exhausted and the "
                        f"outcome is still unknown. Reconcile key {key!r} before retrying."
                    ) from exc
                return self._resolve_unknown(
                    key, fn, on_unknown, probe, naturally_idempotent, attempt + 1)

            job_id = self._extract_job_id(result)
            if job_id is not None:
                self.store.bind_job(key, job_id)
            self.store.succeed(key, result)
            return result

        raise RetriesExhausted(f"retry budget exhausted on key {key!r}")  # unreachable

    def _pause(self, attempt: int, retry_after_ms: float | None) -> None:
        delay_ms = (
            float(retry_after_ms)
            if retry_after_ms is not None
            else self.policy.backoff.delay_ms(attempt, self._rng)
        )
        self._sleep(delay_ms / 1000.0)
