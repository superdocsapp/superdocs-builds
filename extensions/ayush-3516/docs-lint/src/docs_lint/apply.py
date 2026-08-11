"""Applying approved fixes. The only place anything is written to a document.

Every entry point here demands a `Decisions` object, which cannot be built from findings alone —
it comes from the review UI or a decisions file a human edited. That is what makes "`--fix` never
applies anything without approval" a property of the code rather than a promise.

Three rules govern what lands:

*Approved only.* A finding with no decision is not applied. Silence is not consent.

*Verified before written.* A local fix is applied only if the text at its anchor still reads
exactly as the finding said it did. If the document moved underneath us, the fix is skipped and
reported, never applied to a guess.

*Reported honestly.* Anything not applied is named, with the reason. "Applied 3 of 4" is a useful
sentence; "done" would not be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .model import Decisions, FileResult, Finding, Source
from .state import write_atomic
from .superdocs.client import SuperDocsClient
from .superdocs.errors import SuperDocsError


@dataclass
class AppliedFix:
    path: str
    finding_id: str
    rule_id: str
    summary: str


@dataclass
class SkippedFix:
    path: str
    finding_id: str
    rule_id: str
    reason: str


@dataclass
class ApplyResult:
    """What actually happened, in enough detail to report without overstating."""

    applied: list[AppliedFix] = field(default_factory=list)
    skipped: list[SkippedFix] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    rejected: int = 0

    @property
    def ok(self) -> bool:
        return not self.skipped

    def summary_line(self) -> str:
        parts = [f"{len(self.applied)} fix(es) applied across {len(self.files_written)} file(s)"]
        if self.rejected:
            parts.append(f"{self.rejected} rejected")
        if self.skipped:
            parts.append(f"{len(self.skipped)} could not be applied")
        return ", ".join(parts)


def apply_to_results(
    results: list[FileResult],
    decisions: Decisions,
    *,
    root: Path,
    client: SuperDocsClient | None = None,
    sessions: dict[str, str] | None = None,
    job_ids: dict[str, str] | None = None,
) -> ApplyResult:
    """Apply every approved fix, file by file.

    `sessions` and `job_ids` map a document path to the SuperDocs session and job that produced its
    proposals; they come from the run state, so a `fix` can be completed by a later process.
    """
    outcome = ApplyResult()
    sessions = sessions or {}
    job_ids = job_ids or {}

    for result in results:
        if not result.findings:
            continue
        approved = [f for f in result.findings if decisions.is_approved(f.finding_id)]
        outcome.rejected += len(result.findings) - len(approved)
        if not approved:
            continue

        path = root / result.path
        try:
            original_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            for finding in approved:
                outcome.skipped.append(
                    SkippedFix(
                        result.path, finding.finding_id, finding.rule_id, f"unreadable: {exc}"
                    )
                )
            continue

        text = original_text
        model_findings = [f for f in approved if f.source is Source.SUPERDOCS]
        local_findings = [f for f in approved if f.source is not Source.SUPERDOCS]

        if model_findings:
            text = _apply_via_superdocs(
                result=result,
                approved=model_findings,
                decisions=decisions,
                client=client,
                session_id=sessions.get(result.path),
                job_id=job_ids.get(result.path),
                current=text,
                outcome=outcome,
            )

        if local_findings:
            text = _apply_local(local_findings, text, path=result.path, outcome=outcome)

        if text != original_text:
            write_atomic(path, text)
            outcome.files_written.append(result.path)

    return outcome


def _apply_local(findings: list[Finding], text: str, *, path: str, outcome: ApplyResult) -> str:
    """Patch approved local fixes into the text, latest offset first.

    Working backwards means each replacement cannot invalidate the offsets of the ones not yet
    applied, so no offset arithmetic is needed and there is nothing to get subtly wrong.
    """
    fixable = sorted(
        (f for f in findings if f.is_fixable and f.original is not None),
        key=lambda f: f.anchor.start_char,
        reverse=True,
    )
    for finding in findings:
        if not finding.is_fixable:
            outcome.skipped.append(
                SkippedFix(
                    path,
                    finding.finding_id,
                    finding.rule_id,
                    "this rule reports but does not propose a correction",
                )
            )

    # Two rules can legitimately target the same span - a heading that is both Title Case and ends
    # in a full stop, for instance. Applying the first invalidates the second, so overlaps are
    # detected here rather than discovered as a confusing "text not found" failure. The first fix
    # wins, the rest are reported as superseded, and a second `check` catches whatever remains.
    claimed: list[tuple[int, int]] = []

    for finding in fixable:
        anchor = finding.anchor
        original = finding.original or ""
        replacement = finding.replacement or ""

        if any(anchor.start_char < end and start < anchor.end_char for start, end in claimed):
            outcome.skipped.append(
                SkippedFix(
                    path,
                    finding.finding_id,
                    finding.rule_id,
                    "superseded by another approved fix on the same text; "
                    "re-run docs-lint to catch what remains",
                )
            )
            continue

        if text[anchor.start_char : anchor.end_char] == original:
            start, end = anchor.start_char, anchor.end_char
        else:
            # The document moved, most likely because a model fix landed first. Look for the exact
            # text instead of trusting a stale offset; a fix applied to the wrong span would be
            # worse than one not applied at all.
            found = text.find(original)
            if found < 0 or not original:
                outcome.skipped.append(
                    SkippedFix(
                        path,
                        finding.finding_id,
                        finding.rule_id,
                        "the text this fix targets is no longer present",
                    )
                )
                continue
            start, end = found, found + len(original)

        claimed.append((anchor.start_char, anchor.end_char))

        text = text[:start] + replacement + text[end:]
        outcome.applied.append(
            AppliedFix(
                path, finding.finding_id, finding.rule_id, f"{original!r} -> {replacement!r}"
            )
        )
    return text


def _apply_via_superdocs(
    *,
    result: FileResult,
    approved: list[Finding],
    decisions: Decisions,
    client: SuperDocsClient | None,
    session_id: str | None,
    job_id: str | None,
    current: str,
    outcome: ApplyResult,
) -> str:
    """Submit per-item decisions to SuperDocs, then export the result.

    Every proposal for this document is listed explicitly, approved or rejected, in one review.
    That is the API's own batch shape, and it is why rejecting one finding leaves the others alone
    instead of discarding the batch.
    """
    model_findings = [f for f in result.findings if f.source is Source.SUPERDOCS and f.change_id]
    if client is None or not session_id or not job_id:
        for finding in approved:
            outcome.skipped.append(
                SkippedFix(
                    result.path,
                    finding.finding_id,
                    finding.rule_id,
                    "no SuperDocs session recorded for this document; re-run the check",
                )
            )
        return current

    verdicts = [
        (f.change_id, decisions.is_approved(f.finding_id)) for f in model_findings if f.change_id
    ]
    if not verdicts:
        return current

    try:
        client.approve(session_id=session_id, job_id=job_id, decisions=verdicts)
        exported = client.export(session_id=session_id, fmt="markdown")
    except SuperDocsError as exc:
        for finding in approved:
            outcome.skipped.append(
                SkippedFix(result.path, finding.finding_id, finding.rule_id, f"SuperDocs: {exc}")
            )
        return current

    for finding in approved:
        if finding.source is Source.SUPERDOCS:
            outcome.applied.append(
                AppliedFix(
                    result.path,
                    finding.finding_id,
                    finding.rule_id,
                    finding.explanation or "style guide correction",
                )
            )
    return exported
