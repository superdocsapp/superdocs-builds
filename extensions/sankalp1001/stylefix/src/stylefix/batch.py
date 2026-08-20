"""Batch mode: run the whole docs set, report the violation profile by rule.

The card asks for the profile "so the team can see which guidance is being ignored
most" — the output is a ranked table of rules, not a pile of per-file reports.

The brief also asks, in as many words, for restraint: "if your build measures
something or runs in a loop, give it a small-sample mode and a stopping rule, so you
learn this on day one and not on day nine." Both live here, and both are on by
default. A run that would exceed its operation budget stops and says so; it does not
quietly spend the rest of the month.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .client import SuperDocsClient
from .lint import LintResult, lint_document


@dataclass
class StoppingRule:
    """When to stop early. Every field is a reason a run may end short of the set."""

    max_operations: int = 50
    max_documents: int | None = None
    stop_after_failures: int = 3

    def exceeded(self, operations: int, documents: int, failures: int) -> str | None:
        if operations >= self.max_operations:
            return f"operation budget reached ({operations}/{self.max_operations})"
        if self.max_documents is not None and documents >= self.max_documents:
            return f"document limit reached ({documents})"
        if failures >= self.stop_after_failures:
            return f"{failures} consecutive failures — stopping rather than burning budget"
        return None


@dataclass
class BatchReport:
    guide: str
    applied_changes: bool = False
    results: list[LintResult] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    stopped_because: str | None = None
    skipped: list[str] = field(default_factory=list)

    @property
    def operations(self) -> int:
        return sum(r.operations for r in self.results)

    def profile(self) -> list[tuple[str, int, int]]:
        """(rule_id, proposed, applied), ranked by how often the rule is broken."""
        proposed: Counter[str] = Counter()
        applied: Counter[str] = Counter()
        for r in self.results:
            for f in r.findings:
                proposed[f.rule_id] += 1
                if f.applied:
                    applied[f.rule_id] += 1
        return [(rule, n, applied[rule]) for rule, n in proposed.most_common()]

    def render(self) -> str:
        lines = [
            f"Style guide : {self.guide}",
            f"Documents   : {len(self.results)} linted, {len(self.failures)} failed,"
            f" {len(self.skipped)} skipped",
            f"Operations  : {self.operations}",
            f"Mode        : {'applying fixes' if self.applied_changes else 'report only, nothing applied'}",
        ]
        if self.stopped_because:
            lines.append(f"Stopped     : {self.stopped_because}")
        lines.append("")
        profile = self.profile()
        if not profile:
            lines.append("No violations found. Every document complies with this guide.")
            return "\n".join(lines)

        lines.append("Violation profile, most-broken rule first:")
        # In a report-only run nothing was approved, so calling the column "applied"
        # would overstate what happened. It is what the guard cleared.
        second = "applied" if self.applied_changes else "cleared"
        lines.append(f"  {'rule':<32} {'found':>6} {second:>8}  {'refused':>8}")
        for rule, found, applied in profile:
            lines.append(f"  {rule:<32} {found:>6} {applied:>8}  {found - applied:>8}")
        if self.failures:
            lines.append("")
            lines.append("Failed documents:")
            for name, why in self.failures:
                lines.append(f"  {name}: {why}")
        return "\n".join(lines)


def sample(paths: Iterable[Path], size: int | None, seed: int = 0) -> list[Path]:
    """Small-sample mode. Deterministic, so a sampled run is reproducible."""
    ordered = sorted(paths)
    if size is None or size >= len(ordered):
        return ordered
    import random

    return sorted(random.Random(seed).sample(ordered, size))


def lint_batch(
    client: SuperDocsClient,
    documents: Iterable[Path],
    guide: str | Path,
    session_prefix: str,
    apply: bool = False,
    stopping: StoppingRule | None = None,
    sample_size: int | None = None,
    on_event: Callable[[str, str], None] | None = None,
) -> BatchReport:
    """Lint a docs set against one guide.

    Defaults to `apply=False`: a batch run reports the profile without editing
    anything, because the first question a docs lead asks is which guidance is being
    ignored, not "please rewrite 400 pages".
    """
    say = on_event or (lambda stage, msg: None)
    rule = stopping or StoppingRule()
    chosen = sample([Path(p) for p in documents], sample_size)
    report = BatchReport(Path(guide).name, applied_changes=apply)
    consecutive_failures = 0

    for i, doc in enumerate(chosen):
        stop = rule.exceeded(report.operations, len(report.results), consecutive_failures)
        if stop:
            report.stopped_because = stop
            report.skipped = [p.name for p in chosen[i:]]
            say("stop", f"{stop}; {len(report.skipped)} document(s) not attempted")
            break
        try:
            say("lint", f"{doc.name} ({i + 1}/{len(chosen)})")
            before = client.usage.operations
            result = lint_document(
                client, doc, guide, f"{session_prefix}-{i:03d}",
                apply=apply, export_format=None, on_event=on_event,
            )
            # The client's counter is cumulative; the delta is what this document
            # cost. Summing snapshots inflates the total and trips the stopping rule
            # early, skipping documents the budget could afford.
            result.operations = client.usage.operations - before
            report.results.append(result)
            consecutive_failures = 0
        except Exception as exc:  # reported, never swallowed
            report.failures.append((doc.name, f"{type(exc).__name__}: {exc}"))
            consecutive_failures += 1
            say("fail", f"{doc.name}: {exc}")

    return report
