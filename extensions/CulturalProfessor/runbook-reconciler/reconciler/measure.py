"""Scoring the checker against the key, with the method fixed in advance.

`fixtures/expected.yaml` was written before the checker existed. This module
compares what the checker produces against it and reports precision, recall and
the cried-wolf rate. The raw comparison is written to `docs/measurement.json` so
the numbers in the README can be recomputed by anyone who doubts them.

## How a produced finding is matched to an expected one

Three things must agree: **the page** (or both being estate-level), **the kind**,
and **the asserted string** — the key's `asserted_contains` has to appear
somewhere in the finding's subject, the claim's asserted text, or what was
observed.

Subjects are deliberately *not* matched. `alert:PaymentsApiHighLatency:threshold`
is an internal naming choice and the key was written before those choices were
made; scoring on it would measure whether the key's author guessed the
implementation's vocabulary, which is not a property anybody cares about. The
page, the kind and the value are the finding.

## What each number means

- **precision** — of the contradictions reported, how many the key expects.
- **recall** — of the contradictions the key expects, how many were reported.
- **cried wolf** — false positives as a fraction of everything reported. The
  same information as precision, named the way an on-call engineer experiences
  it, because that is the number that decides whether the tool survives.
- **unverifiable** — counted, never folded into either. A rule 4 violation
  (something the key says is uncheckable reported as agreeing) is listed
  separately and is a failure, not a miss.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from reconciler.claims import Claim, Finding
from reconciler.config import PROJECT_ROOT


@dataclass
class Score:
    expected: int = 0
    reported: int = 0
    matched: int = 0
    misses: list[dict[str, str]] = field(default_factory=list)
    false_positives: list[dict[str, str]] = field(default_factory=list)
    rule_four_violations: list[dict[str, str]] = field(default_factory=list)
    unverifiable: int = 0
    agrees: int = 0

    @property
    def precision(self) -> float:
        return self.matched / self.reported if self.reported else 0.0

    @property
    def recall(self) -> float:
        return self.matched / self.expected if self.expected else 0.0

    @property
    def cried_wolf(self) -> float:
        return len(self.false_positives) / self.reported if self.reported else 0.0

    def lines(self) -> list[str]:
        return [
            f"expected {self.expected} contradictions, reported {self.reported}, "
            f"matched {self.matched}",
            f"precision {self.precision:.3f} · recall {self.recall:.3f} · "
            f"cried wolf {self.cried_wolf:.3f}",
            f"{self.agrees} claims verified · {self.unverifiable} unverifiable (counted, "
            f"never assumed correct)",
            *[f"  MISSED    {m['id']}: {m['why']}" for m in self.misses],
            *[f"  EXTRA     page {f['page']}: {f['subject']}" for f in self.false_positives],
            *[f"  RULE 4    {v['subject']}: {v['why']}" for v in self.rule_four_violations],
        ]


def load_key(path: Path | None = None) -> dict[str, Any]:
    path = path or PROJECT_ROOT / "fixtures" / "expected.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def score(findings: list[Finding], claims: list[Claim], key: dict[str, Any] | None = None) -> Score:
    key = key or load_key()
    asserted_by_claim = {claim.claim_id: claim.asserted for claim in claims}
    reported = [f for f in findings if f.verdict == "contradicts"]
    expected = list(key["expected_findings"])

    result = Score(
        expected=len(expected),
        reported=len(reported),
        unverifiable=sum(1 for f in findings if f.verdict == "unverifiable"),
        agrees=sum(1 for f in findings if f.verdict == "agrees"),
    )

    unmatched = list(reported)
    for entry in expected:
        hit = next(
            (f for f in unmatched if _matches(entry, f, asserted_by_claim)),
            None,
        )
        if hit:
            unmatched.remove(hit)
            result.matched += 1
        else:
            result.misses.append({"id": entry["id"], "why": entry.get("why", "")[:120]})

    result.false_positives = [
        {"page": f.page_id or "estate", "subject": f.subject, "detail": f.detail[:120]}
        for f in unmatched
    ]
    result.rule_four_violations = _rule_four(findings, claims, key)
    return result


def _matches(entry: dict[str, Any], finding: Finding, asserted: dict[str, str]) -> bool:
    if (entry.get("page") or None) != (finding.page_id or None):
        return False
    if entry.get("kind") != finding.kind:
        return False
    haystack = " ".join(
        [
            finding.subject,
            finding.observed or "",
            asserted.get(finding.claim_id or "", ""),
        ]
    ).lower()
    return str(entry.get("asserted_contains", "")).lower() in haystack


def _rule_four(
    findings: list[Finding], claims: list[Claim], key: dict[str, Any]
) -> list[dict[str, str]]:
    """Anything the key says is uncheckable that was reported as checked.

    Scored apart from precision on purpose. A miss is a gap; this is a lie, and
    averaging the two into one number would let a tool trade the second for the
    first and look better for it.
    """
    by_claim = {claim.claim_id: claim for claim in claims}
    violations: list[dict[str, str]] = []
    for case in key.get("unverifiable_cases") or []:
        page = str(case.get("page"))
        about = str(case.get("about", "")).lower()
        for finding in findings:
            if finding.page_id != page or finding.verdict == "unverifiable":
                continue
            claim = by_claim.get(finding.claim_id or "")
            text = f"{finding.subject} {claim.asserted if claim else ''}".lower()
            if about and about[:20] in text:
                violations.append(
                    {
                        "subject": finding.subject,
                        "why": f"the key says this cannot be checked; reported {finding.verdict}",
                    }
                )
    return violations


def write_raw(score_result: Score, findings: list[Finding], path: Path | None = None) -> Path:
    """Commit the raw data, not just the summary.

    The brief asks for measurement with the method stated and the raw data
    committed. A percentage in a README that nobody can recompute is a claim,
    not a measurement.
    """
    path = path or PROJECT_ROOT / "docs" / "measurement.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method": (
            "expected.yaml was written before the checker existed. A produced finding "
            "matches an expected one when the page, the kind and the asserted string all "
            "agree; subjects are not scored, being an internal naming choice made after "
            "the key was written."
        ),
        "score": {
            **asdict(score_result),
            "precision": round(score_result.precision, 4),
            "recall": round(score_result.recall, 4),
            "cried_wolf": round(score_result.cried_wolf, 4),
        },
        "findings": [
            {
                "rule_id": f.rule_id,
                "page_id": f.page_id,
                "kind": f.kind,
                "subject": f.subject,
                "verdict": f.verdict,
                "observed": f.observed,
                "evidence": f"{f.evidence_file}:{f.evidence_line or 1}",
                "tags": list(f.tags),
            }
            for f in sorted(findings, key=lambda f: (f.verdict, f.page_id or "", f.subject))
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = ["Score", "load_key", "score", "write_raw"]
