"""Randomised fault injection.

The three named scenarios in `test_faults.py` are the faults I thought of. This
one generates faults I did not: random operation sequences, random failures at
random attempts, random reconciliation outcomes, random process deaths.

It asserts the invariants that must hold no matter what happened:

  INV1  no operation key is ever applied more than once
  INV2  a key the library reports as SUCCEEDED was applied exactly once —
        never zero, which would be a success it invented
  INV3  a key the library reports as FAILED was never applied

The seed is fixed so a failure reproduces exactly. Override it to explore:

    IDEM_FUZZ_SEED=99 IDEM_FUZZ_RUNS=5000 pytest tests/test_fuzz.py
"""

from __future__ import annotations

import os
import random
from collections import Counter

import pytest

from idem import (
    Idempotent, OutcomeUnknown, Policy, RetriesExhausted,
    TerminalFailure, UnknownPolicy, Verdict,
)
from tests.vectorlib import POLICY_PATH

# 400 in the default suite so `make test` stays quick; `make fuzz` turns it up.
# Coverage is a function of runs x seeds, and CI can afford a bigger number than
# someone waiting at a prompt.
RUNS = int(os.environ.get("IDEM_FUZZ_RUNS", "400"))
SEED = int(os.environ.get("IDEM_FUZZ_SEED", "20260823"))

# Every fault the transport can produce, and — crucially — whether the server
# applied the edit before the failure. That second column is the ground truth
# the library cannot see, which is the entire problem it exists to handle.
FAULTS = [
    # (label,               applied_before_failing, status, error,        sent)
    ("ok",                   True,  None, None,               True),
    ("read-timeout-applied", True,  None, "ReadTimeout",      True),
    ("500-after-apply",      True,  500,  "HTTPStatusError",  True),
    ("500-before-apply",     False, 503,  "HTTPStatusError",  True),
    ("connect-timeout",      False, None, "ConnectTimeout",   False),
    ("dns",                  False, None, "DNSError",         False),
    ("rate-limited",         False, 429,  "HTTPStatusError",  True),
    ("conflict",             False, 409,  "HTTPStatusError",  True),
    ("unprocessable",        False, 422,  "HTTPStatusError",  True),
    ("nonsense",             False, None, "GremlinsInTheWire", True),
]


class FuzzError(Exception):
    def __init__(self, status, sent):
        super().__init__(f"fuzz(status={status}, sent={sent})")
        self.status, self.sent = status, sent


def _typed(name, status, sent):
    return type(name, (FuzzError,), {})(status, sent)


class FuzzServer:
    """Counts applies per key. This is ground truth; the library never sees it."""

    def __init__(self):
        self.applies = Counter()

    def call(self, key, fault):
        label, applied, status, error, sent = fault
        if applied:
            self.applies[key] += 1          # the billable, document-changing bit
        if error is None and status is None:
            return {"job_id": f"job-{key}", "status": "completed"}
        raise _typed(error or "HTTPStatusError", status, sent)


def _run_one(rng) -> tuple[FuzzServer, Idempotent, list[str]]:
    import tempfile
    from pathlib import Path

    server = FuzzServer()
    idem = Idempotent(
        Path(tempfile.mkdtemp()) / "fuzz.db",
        Policy.load(POLICY_PATH),
        sleep=lambda _s: None,
        rng=random.Random(rng.random()),
    )

    keys = [f"k{n}" for n in range(rng.randint(1, 4))]
    log = []

    for _ in range(rng.randint(1, 12)):
        key = rng.choice(keys)
        fault = rng.choice(FAULTS)
        log.append(f"{key}:{fault[0]}")

        # A probe that tells the truth about what the server did. Reconciliation
        # is only sound when the answer is honest; a lying probe is the caller's
        # bug, not the library's.
        def probe(record, _k=key):
            return (Verdict.APPLIED, {"job_id": f"job-{_k}", "status": "completed"}) \
                if server.applies[_k] else Verdict.NOT_APPLIED

        # RETRY_ANYWAY is deliberately excluded: it is the documented unsafe
        # path, where a second apply is the caller's stated intent (SPEC.md R12).
        policy = rng.choice([UnknownPolicy.REFUSE, UnknownPolicy.RECONCILE])

        if rng.random() < 0.15:
            # A process died mid-flight: an in-flight record left by a pid that
            # is not us. Same shape the restart test builds deliberately.
            rec = idem.store.get(key)
            if rec is None:
                idem.store.claim(key)
            with idem.store._connect() as conn:
                conn.execute(
                    "UPDATE operations SET state='in_flight', owner_pid=999999 WHERE key=?",
                    (key,),
                )
            log.append(f"{key}:CRASH")

        try:
            idem.run(key, lambda _f=fault, _k=key: server.call(_k, _f),
                     on_unknown=policy, probe=probe)
        except (OutcomeUnknown, TerminalFailure, RetriesExhausted):
            pass

    return server, idem, keys, log


@pytest.mark.parametrize("batch", range(10))
def test_no_double_apply_under_random_faults(batch):
    rng = random.Random(SEED + batch)
    for n in range(RUNS // 10):
        server, idem, keys, log = _run_one(rng)
        trail = " → ".join(log)

        for key in keys:
            applied = server.applies[key]
            state = idem.store.state_of(key)

            assert applied <= 1, (
                f"INV1 VIOLATED: key {key!r} applied {applied} times.\n"
                f"  seed={SEED + batch} run={n}\n  sequence: {trail}"
            )
            if state == "succeeded":
                assert applied == 1, (
                    f"INV2 VIOLATED: key {key!r} reported SUCCEEDED but the server "
                    f"applied it {applied} times.\n  seed={SEED + batch} run={n}\n"
                    f"  sequence: {trail}"
                )
            if state == "failed":
                assert applied == 0, (
                    f"INV3 VIOLATED: key {key!r} reported FAILED but the server "
                    f"applied it {applied} times.\n  seed={SEED + batch} run={n}\n"
                    f"  sequence: {trail}"
                )


def test_the_fuzzer_would_notice_a_double_apply():
    """A fuzzer that cannot fail proves nothing. This drives the same faults
    through a caller that ignores the library and retries blindly, and confirms
    the invariant it checks is one a broken client actually breaks."""
    server = FuzzServer()
    applied_twice = next(f for f in FAULTS if f[0] == "read-timeout-applied")

    for _ in range(2):                      # the naive retry: no key, no record
        try:
            server.call("k", applied_twice)
        except FuzzError:
            pass

    assert server.applies["k"] == 2, "the harness cannot detect a double apply"
