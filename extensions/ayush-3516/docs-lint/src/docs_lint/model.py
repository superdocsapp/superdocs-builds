"""The core vocabulary: what a finding is, where it points, and what we are willing to claim.

Two invariants are encoded here as types rather than trusted to discipline:

*Never bluff.* Every file ends a run with exactly one `Verdict`. There is no way to construct a
summary that reports "clean" for a file that was not actually checked - `Verdict.clean()` is the
only constructor that produces a clean verdict, and it requires the checks that ran.

*Never write without approval.* `Decisions` is the only thing the applier accepts, and it can only
be built from an explicit per-finding decision. A list of findings cannot be coerced into one.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    """How much a rule violation matters. `OFF` disables the rule entirely."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    OFF = "off"

    @classmethod
    def parse(cls, raw: Any, *, default: Severity = INFO) -> Severity:
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            return default

    @property
    def rank(self) -> int:
        return {Severity.ERROR: 3, Severity.WARNING: 2, Severity.INFO: 1, Severity.OFF: 0}[self]


class Source(StrEnum):
    """Which pass produced a finding.

    Worth keeping visible in output: a reviewer treats "the linter's regex matched" and "a model
    judged this against your style guide" differently, and should be able to tell them apart.
    """

    LOCAL = "local"
    SUPERDOCS = "superdocs"


class Anchor(BaseModel):
    """Where a finding lives, expressed several ways because each consumer needs a different one.

    `heading_path` survives the file shifting by a few lines, which line numbers do not; line and
    character offsets are what an editor and SARIF want; `chunk_id` is what SuperDocs needs to land
    an approved correction in one block instead of replacing the file.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_char: int = Field(default=0, ge=0)
    end_char: int = Field(default=0, ge=0)
    heading_path: tuple[str, ...] = ()
    chunk_id: str | None = None

    @property
    def location(self) -> str:
        """Human-readable position: `docs/guide.md:12` or `docs/guide.md:12-15`."""
        if self.end_line != self.start_line:
            return f"{self.path}:{self.start_line}-{self.end_line}"
        return f"{self.path}:{self.start_line}"

    @property
    def section(self) -> str:
        return " > ".join(self.heading_path) if self.heading_path else "(document root)"

    def overlaps(self, other: Anchor) -> bool:
        return (
            self.path == other.path
            and self.start_line <= other.end_line
            and other.start_line <= self.end_line
        )


class Finding(BaseModel):
    """One rule violation, optionally carrying a proposed correction.

    A finding with `replacement is None` can be reported but never fixed - which is correct for
    rules that can detect a problem without knowing the right answer.
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    severity: Severity
    message: str
    anchor: Anchor
    source: Source = Source.LOCAL
    replacement: str | None = None
    original: str | None = None
    explanation: str | None = None
    #: Set only for SuperDocs findings: the id the approval API expects back.
    change_id: str | None = None

    @property
    def finding_id(self) -> str:
        """A stable id for this finding, used to record a human decision against it.

        Derived from content rather than position in a list, so a decision file stays meaningful
        if findings are re-ordered, and so re-running produces the same ids for the same problems.
        """
        if self.change_id:
            return self.change_id
        digest = hashlib.sha256(
            "\x00".join(
                [
                    self.anchor.path,
                    self.rule_id,
                    str(self.anchor.start_line),
                    str(self.anchor.start_char),
                    self.message,
                ]
            ).encode()
        ).hexdigest()
        return f"f_{digest[:12]}"

    @property
    def is_fixable(self) -> bool:
        return self.replacement is not None


class VerdictKind(StrEnum):
    """The four honest things that can be said about a file after a run.

    Note what is missing: there is no "probably fine" and no "assumed clean".
    """

    CLEAN = "clean"
    FINDINGS = "findings"
    SKIPPED = "skipped"
    FAILED = "failed"


class Verdict(BaseModel):
    """What we are willing to claim about one file, and why.

    Built through the four constructors below rather than directly, so that a clean verdict cannot
    be produced by accident. `CLEAN` requires naming the checks that actually ran; if the SuperDocs
    pass was skipped or failed, the verdict is `SKIPPED` or `FAILED`, never `CLEAN`.
    """

    model_config = ConfigDict(frozen=True)

    kind: VerdictKind
    reason: str | None = None
    checks_run: tuple[str, ...] = ()

    @classmethod
    def clean(cls, *, checks_run: tuple[str, ...]) -> Verdict:
        if not checks_run:
            raise ValueError(
                "a clean verdict must name the checks that ran; "
                "a file nobody checked is skipped, not clean"
            )
        return cls(kind=VerdictKind.CLEAN, checks_run=checks_run)

    @classmethod
    def findings(cls, *, checks_run: tuple[str, ...]) -> Verdict:
        return cls(kind=VerdictKind.FINDINGS, checks_run=checks_run)

    @classmethod
    def skipped(cls, reason: str) -> Verdict:
        return cls(kind=VerdictKind.SKIPPED, reason=reason)

    @classmethod
    def failed(cls, reason: str) -> Verdict:
        return cls(kind=VerdictKind.FAILED, reason=reason)

    @property
    def is_trustworthy(self) -> bool:
        """True only when the file was genuinely examined to completion."""
        return self.kind in {VerdictKind.CLEAN, VerdictKind.FINDINGS}


class FileResult(BaseModel):
    """Everything a run concluded about one file."""

    model_config = ConfigDict(frozen=True)

    path: str
    verdict: Verdict
    findings: tuple[Finding, ...] = ()
    from_cache: bool = False
    seconds: float = 0.0
    ops_charged: int = 0

    @property
    def worst_severity(self) -> Severity | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: s.rank)

    def gating_findings(self, error_on: frozenset[Severity]) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity in error_on)


class Decision(BaseModel):
    """A human's answer about one finding. There is no third option and no default."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    approved: bool
    note: str | None = None


class Decisions(BaseModel):
    """The only key that unlocks writing to disk.

    Deliberately a distinct type from `list[Finding]`. Nothing in the codebase converts findings
    into decisions implicitly; a `Decisions` can only come from the review server or a decisions
    file a human edited. That makes "fix never applies anything without approval" a property of the
    type system rather than a promise in a README.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    decisions: tuple[Decision, ...] = ()

    @property
    def by_id(self) -> dict[str, Decision]:
        return {d.finding_id: d for d in self.decisions}

    def approved_ids(self) -> frozenset[str]:
        return frozenset(d.finding_id for d in self.decisions if d.approved)

    def is_approved(self, finding_id: str) -> bool:
        """Unknown findings are rejected.

        The safe default when a decision is missing is that nothing happens - silence is not
        consent, and a finding that appeared after the review was written has not been reviewed.
        """
        decision = self.by_id.get(finding_id)
        return bool(decision and decision.approved)

    def covers(self, findings: tuple[Finding, ...]) -> tuple[str, ...]:
        """Finding ids present in `findings` but absent from this decision set."""
        known = self.by_id
        return tuple(f.finding_id for f in findings if f.finding_id not in known)


class RunSummary(BaseModel):
    """The whole run, and the single place the exit code is decided."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    results: tuple[FileResult, ...] = ()
    stage_seconds: dict[str, float] = Field(default_factory=dict)
    ops_charged: int = 0
    degraded: tuple[str, ...] = ()

    @property
    def all_findings(self) -> tuple[Finding, ...]:
        return tuple(f for r in self.results for f in r.findings)

    @property
    def is_partial(self) -> bool:
        """True if any file was skipped, failed, or a stage degraded.

        A partial run may still exit zero - not every skip is an error - but it must never be
        described as a clean bill of health for the whole set.
        """
        return bool(self.degraded) or any(not r.verdict.is_trustworthy for r in self.results)

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(VerdictKind, 0)
        for result in self.results:
            counts[result.verdict.kind] += 1
        return {kind.value: n for kind, n in counts.items()}

    def exit_code(self, error_on: frozenset[Severity]) -> int:
        """0 clean, 1 gating findings, 2 something could not be checked.

        A file that failed outranks findings: "I could not check this" is a worse thing to discover
        in CI than "I checked this and it has problems", because the first hides the second.
        """
        if any(r.verdict.kind is VerdictKind.FAILED for r in self.results):
            return 2
        if any(r.gating_findings(error_on) for r in self.results):
            return 1
        return 0

    def headline(self, error_on: frozenset[Severity]) -> str:
        """One honest sentence. Never says 'clean' about files it did not check."""
        counts = self.counts()
        checked = counts["clean"] + counts["findings"]
        gating = sum(len(r.gating_findings(error_on)) for r in self.results)
        total = len(self.all_findings)

        if counts["failed"]:
            return (
                f"{counts['failed']} of {len(self.results)} files could not be checked; "
                f"{total} findings in the {checked} that were"
            )
        if total == 0 and checked:
            suffix = f" ({counts['skipped']} skipped)" if counts["skipped"] else ""
            return f"{checked} files checked, no findings{suffix}"
        if not checked:
            return f"nothing was checked ({counts['skipped']} skipped)"
        return f"{total} findings in {checked} files ({gating} at gating severity)"
