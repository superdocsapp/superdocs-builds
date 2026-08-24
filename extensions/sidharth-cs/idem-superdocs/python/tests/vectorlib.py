"""Shared machinery for running vectors.json.

Kept out of the test module so the fault harness can reuse the scripted
operation and the delay recorder.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from idem import Idempotent, Policy, UnknownPolicy, Verdict

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "policy.json"
VECTORS_PATH = ROOT / "vectors.json"


class ScriptedError(Exception):
    """An error shaped the way the library reads errors: a status if there was
    a response, and an explicit attestation of whether the request was sent.

    __name__ is set per instance so one class can impersonate ReadTimeout,
    ConnectTimeout or anything else a vector names, which keeps the vectors
    honest about matching on the error's *name* rather than on its identity.
    """

    def __init__(self, class_name, status=None, sent=True, retry_after_ms=None):
        super().__init__(f"{class_name}(status={status}, sent={sent})")
        self.class_name = class_name
        self.status = status
        self.sent = sent
        self.retry_after_ms = retry_after_ms


def _typed(class_name):
    return type(class_name, (ScriptedError,), {})


class ScriptedOperation:
    """Consumes a vector's attempt script. Counts executions, because
    'executions' is the observable form of 'did we double-apply'."""

    def __init__(self, attempts):
        self.script = list(attempts)
        self.executions = 0

    def __call__(self):
        self.executions += 1
        if not self.script:
            raise AssertionError(
                f"the operation ran {self.executions} times but the vector only "
                f"scripted {self.executions - 1} attempts"
            )
        step = self.script.pop(0)
        if step["event"] == "ok":
            return step.get("result")
        cls = _typed(step["class"])
        raise cls(
            step["class"],
            status=step.get("status"),
            sent=step.get("sent", True),
            retry_after_ms=step.get("retry_after_ms"),
        )


def load_vectors():
    return json.loads(VECTORS_PATH.read_text())["vectors"]


def load_policy():
    return Policy.load(POLICY_PATH)


def build(tmp_path, policy=None, *, job_probe=None, seed=1234):
    """An Idempotent whose sleeps are captured rather than taken, so the suite
    is deterministic and never actually waits."""
    delays_ms = []
    idem = Idempotent(
        tmp_path / "idem.db",
        policy or load_policy(),
        job_probe=job_probe,
        sleep=lambda seconds: delays_ms.append(seconds * 1000.0),
        rng=random.Random(seed),
    )
    return idem, delays_ms


def probe_returning(vector):
    """The probe a vector asks for, or None when the vector never reconciles."""
    verdict = vector.get("reconcile_verdict")
    if verdict is None:
        return None
    v = Verdict(verdict)
    result = vector.get("reconcile_result")
    return lambda _record: (v, result) if result is not None else v


UNKNOWN_POLICIES = {p.value: p for p in UnknownPolicy}
