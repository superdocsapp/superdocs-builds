"""The decision table, loaded from data.

Nothing in this module knows which status code means a conflict, or which
error name means the answer was lost. It knows how to match an observation
against a rule and how to compute a jittered delay. Every judgement lives in
policy.json, which both implementations load (SPEC.md R6, R7).

Deliberately so: a test greps this file and the runner for status-code
literals and error class names, and fails if it finds any.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

OUTCOMES = ("success", "retryable", "terminal", "unknown")
CONDITIONS = ("status", "status_range", "error", "sent")


class MalformedPolicy(ValueError):
    """The table is not usable. Raised at load time, never at decision time —
    a retry policy that fails open halfway through a run is worse than one
    that refuses to start."""


@dataclass(frozen=True)
class Rule:
    id: str
    outcome: str
    why: str
    honour_retry_after: bool = False
    requires_reconciliation: bool = False


@dataclass(frozen=True)
class Backoff:
    base_ms: float
    max_ms: float
    multiplier: float
    max_attempts: int

    def ceiling_ms(self, attempt: int) -> float:
        """The upper bound for this attempt's delay. Public because the test
        vectors assert against it: seeded RNGs are not portable between
        languages, so vectors check the bound rather than the value (R11)."""
        return min(self.max_ms, self.base_ms * (self.multiplier**attempt))

    def delay_ms(self, attempt: int, rng: random.Random) -> float:
        # Full jitter. Equal and decorrelated jitter both keep a floor under
        # the delay, which re-synchronises clients that failed together.
        return rng.uniform(0.0, self.ceiling_ms(attempt))


class Policy:
    def __init__(self, raw: dict) -> None:
        self._validate(raw)
        b = raw["backoff"]
        self.backoff = Backoff(
            base_ms=float(b["base_ms"]),
            max_ms=float(b["max_ms"]),
            multiplier=float(b["multiplier"]),
            max_attempts=int(b["max_attempts"]),
        )
        self._rules = [
            (r["when"], Rule(
                id=r["id"],
                outcome=r["outcome"],
                why=r.get("why", ""),
                honour_retry_after=bool(r.get("honour_retry_after", False)),
                requires_reconciliation=bool(r.get("requires_reconciliation", False)),
            ))
            for r in raw["rules"]
        ]

    @classmethod
    def load(cls, path: str | Path) -> Policy:
        return cls(json.loads(Path(path).read_text()))

    @staticmethod
    def _validate(raw: dict) -> None:
        if raw.get("version") != 1:
            raise MalformedPolicy(f"unsupported policy version: {raw.get('version')!r}")
        rules = raw.get("rules")
        if not rules:
            raise MalformedPolicy("policy has no rules")
        for r in rules:
            if r.get("outcome") not in OUTCOMES:
                raise MalformedPolicy(f"rule {r.get('id')!r}: outcome must be one of {OUTCOMES}")
            for key in r.get("when", {}):
                if key not in CONDITIONS:
                    raise MalformedPolicy(f"rule {r.get('id')!r}: unknown condition {key!r}")
            # The card asks for every decision documented with its reasoning.
            # A rule that classifies a failure without saying why is the thing
            # this build exists to replace, so the loader refuses it.
            if r["outcome"] != "success" and not r.get("why"):
                raise MalformedPolicy(f"rule {r.get('id')!r}: every non-success rule needs a 'why'")
        if rules[-1].get("when") != {}:
            raise MalformedPolicy("the last rule must be a catch-all with an empty 'when'")

    def classify(self, *, status: int | None, error: str | None, sent: bool) -> Rule:
        """First rule whose every condition matches. The catch-all guarantees
        this always returns."""
        for when, rule in self._rules:
            if self._matches(when, status=status, error=error, sent=sent):
                return rule
        raise MalformedPolicy("no rule matched and no catch-all fired")  # unreachable; validated

    @staticmethod
    def _matches(when: dict, *, status: int | None, error: str | None, sent: bool) -> bool:
        if "status" in when and status != when["status"]:
            return False
        if "status_range" in when:
            lo, hi = when["status_range"]
            if status is None or not (lo <= status <= hi):
                return False
        if "error" in when and error != when["error"]:
            return False
        if "sent" in when and sent != when["sent"]:
            return False
        return True
