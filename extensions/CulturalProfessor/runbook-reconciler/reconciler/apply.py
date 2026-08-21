"""Turning approved findings into writes, or into nothing at all.

## Two phases, because Confluence has no transaction

Rule 7 says never leave a multi-page update half applied, and no wiki API on
earth will do that for you. What is actually achievable is stated here rather
than implied:

1. **Prepare every page first.** Re-read it, re-resolve every anchor, compute
   the new body, assert each splice individually and then assert the page as a
   whole differs in exactly as many places as there were approvals. If *any*
   page fails to prepare, nothing is written at all.
2. **Commit, and compensate on failure.** If a write fails after earlier pages
   have landed, the pages already written are restored from the bodies held from
   phase one — a compensating write, version-checked like any other.

That is not atomicity and this module does not call it that. A compensating
write can itself fail, and when it does the run stops immediately and reports
exactly which pages are in which state, because a half-restored batch that
carries on is worse than one that stops and says so.

## Anchors are re-resolved, never trusted

A stored offset belongs to the version it was read from. Between the sweep that
found the drift and the human approving it, somebody may have edited the page.
So the anchor is re-found by heading path and content hash; if the hash has
moved, the passage changed under us and the finding is escalated rather than
guessed at.

## Resume

A crash between a successful write and recording it in the register leaves an
approved, unapplied finding whose anchor no longer resolves *because the fix is
already there*. That is detected explicitly and recorded as applied rather than
being retried, which is what makes "kill it and start again" not write twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from reconciler.claims import Claim, Finding
from reconciler.confluence.local import VersionConflict
from reconciler.confluence.splice import (
    SpliceRefused,
    assert_only_these_ranges_changed,
    assert_single_change,
    splice,
)
from reconciler.extract.storage import Document
from reconciler.register import Register


class PageSource(Protocol):
    """What both `LocalSource` and `ConfluenceSource` provide."""

    def read(self, page_id: str) -> Document: ...

    def write(self, page_id: str, body: str, expected_version: int) -> int: ...

    def comment(self, page_id: str, text: str) -> str: ...


@dataclass
class PagePlan:
    page_id: str
    version: int
    original: str
    updated: str
    finding_ids: list[str] = field(default_factory=list)
    #: `(start, end, replacement)` in ORIGINAL-body coordinates, which stay valid
    #: only because the splices are applied from the end backwards.
    edits: list[tuple[int, int, str]] = field(default_factory=list)
    #: What the page's version became once written. Recorded so the watcher can
    #: recognise the bump as ours rather than re-sweeping on it.
    new_version: int = 0


@dataclass
class ApplyResult:
    applied: list[str] = field(default_factory=list)
    commented: list[str] = field(default_factory=list)
    already_applied: list[str] = field(default_factory=list)
    escalated: list[tuple[str, str]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    rolled_back: list[str] = field(default_factory=list)
    #: Pages left changed after a failed rollback. Never empty silently.
    stranded: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.stranded and not self.conflicts

    def summary_line(self) -> str:
        parts = [f"{len(self.applied)} passages updated"]
        if self.commented:
            parts.append(f"{len(self.commented)} commented for a human")
        if self.already_applied:
            parts.append(f"{len(self.already_applied)} already applied (resumed)")
        if self.escalated:
            parts.append(f"{len(self.escalated)} escalated — the passage moved")
        if self.conflicts:
            parts.append(f"{len(self.conflicts)} version conflicts")
        if self.rolled_back:
            parts.append(f"{len(self.rolled_back)} rolled back")
        if self.stranded:
            parts.append(f"{len(self.stranded)} STRANDED — see the log")
        return " · ".join(parts)


def apply_approved(
    register: Register, source: PageSource, findings: list[Finding] | None = None
) -> ApplyResult:
    findings = findings if findings is not None else register.approved_unapplied()
    result = ApplyResult()
    if not findings:
        return result

    by_page: dict[str, list[Finding]] = {}
    for finding in findings:
        if not finding.page_id:
            # An estate-level finding has no passage. Approving one records the
            # decision; there is nothing to write.
            continue
        by_page.setdefault(finding.page_id, []).append(finding)

    # ------------------------------------------------------------ phase one --
    plans: list[PagePlan] = []
    for page_id, page_findings in sorted(by_page.items()):
        plan = _prepare(page_id, page_findings, register, source, result)
        if plan is None:
            continue
        if plan.finding_ids:
            plans.append(plan)

    if result.escalated and not plans:
        return result

    # ------------------------------------------------------------ phase two --
    written: list[PagePlan] = []
    for plan in plans:
        try:
            plan.new_version = source.write(plan.page_id, plan.updated, plan.version)
        except VersionConflict:
            result.conflicts.append(plan.page_id)
            _rollback(written, source, register, result)
            return result
        except Exception:
            _rollback(written, source, register, result)
            raise
        # Rule 6, recorded the instant the write lands rather than once the
        # whole batch has. It used to sit in the transaction below, which is
        # right for the happy path and wrong for every other one: a batch that
        # failed on its third page had already bumped two page versions, and
        # rolling them back bumped two more -- four versions this tool produced,
        # none of them in the ledger, all of them looking to the watcher like
        # somebody else's edit. It then swept on its own writes, which is the
        # one thing the ledger exists to prevent.
        #
        # The ledger is a record of every version this tool caused, not of the
        # ones it was happy about. Entries are keyed (page_id, version) and
        # writing one for a page that is about to be restored is not a lie: we
        # did write that version.
        if plan.new_version:
            register.record_page_write(plan.page_id, plan.new_version)
        written.append(plan)

    with register.transaction():
        for plan in written:
            for finding_id in plan.finding_ids:
                register.mark_applied(finding_id)
                result.applied.append(finding_id)
    return result


def _prepare(
    page_id: str,
    findings: list[Finding],
    register: Register,
    source: PageSource,
    result: ApplyResult,
) -> PagePlan | None:
    document = source.read(page_id)
    body = document.body
    plan = PagePlan(page_id=page_id, version=document.version, original=body, updated=body)

    # Descending by offset: splicing from the end backwards means every earlier
    # offset is still valid. Doing it forwards means each edit invalidates the
    # ones after it, and the resulting corruption looks like a parser bug.
    prepared: list[tuple[Finding, Claim]] = []
    for finding in findings:
        claim = register.claim(finding.claim_id or "")
        if claim is None:
            result.escalated.append((finding.finding_id, "the claim behind it is gone"))
            continue
        if not claim.anchor.editable:
            _comment(source, page_id, finding, claim, register, result)
            continue
        if not finding.proposed:
            result.escalated.append((finding.finding_id, "no replacement text was produced"))
            continue
        prepared.append((finding, claim))

    for finding, claim in sorted(
        prepared, key=lambda pair: pair[1].anchor.char_start, reverse=True
    ):
        block = document.find_block(claim.anchor.heading_path, claim.anchor.content_hash)
        if block is None:
            if _already_applied(document, claim, finding):
                register.mark_applied(finding.finding_id)
                result.already_applied.append(finding.finding_id)
                continue
            result.escalated.append(
                (
                    finding.finding_id,
                    f"the passage under {' > '.join(claim.anchor.heading_path) or 'the page'} "
                    f"changed after this was reviewed; it needs looking at again",
                )
            )
            continue

        at = _occurrence_at(block.text, claim.asserted, claim.anchor.value_occurrence)
        if at == -1:
            nth = claim.anchor.value_occurrence
            result.escalated.append(
                (
                    finding.finding_id,
                    f"{claim.asserted!r} is no longer in that passage"
                    if not nth
                    else f"that passage no longer holds {nth + 1} occurrences of "
                    f"{claim.asserted!r}",
                )
            )
            continue

        start, end = block.body_range(at, at + len(claim.asserted))
        candidate = splice(plan.updated, start, end, finding.proposed or "")
        try:
            assert_single_change(plan.updated, candidate, start, end)
        except SpliceRefused as refused:
            result.escalated.append((finding.finding_id, str(refused)))
            continue
        plan.updated = candidate
        plan.finding_ids.append(finding.finding_id)
        plan.edits.append((start, end, finding.proposed or ""))

    if plan.finding_ids:
        # The assertion no single splice can make: that they did not interfere
        # with each other. Because the splices run from the end backwards, the
        # offsets recorded above are all still valid in the ORIGINAL body, which
        # is the coordinate system this check needs.
        assert_only_these_ranges_changed(plan.original, plan.updated, plan.edits)
    return plan


def _occurrence_at(text: str, value: str, nth: int) -> int:
    """Where the `nth` occurrence of `value` starts, or -1.

    `str.find` was here, and for a passage saying the same wrong thing twice it
    corrected the first one under both anchors — one splice landing twice,
    reported as two fixes. The ordinal comes from the claim, which counted it
    off the same string at extraction, so the two cannot disagree about which
    `800ms` this finding is about.

    Returning -1 when the passage no longer holds that many occurrences is the
    right answer rather than a fallback to the first: fewer of them than there
    were means the passage changed, and a changed passage escalates.
    """
    at = -1
    for _ in range(nth + 1):
        at = text.find(value, at + 1)
        if at == -1:
            return -1
    return at


def _already_applied(document: Document, claim: Claim, finding: Finding) -> bool:
    """Did a previous run write this before it was recorded?

    The crash window is between the successful PUT and the register update. The
    evidence that it landed is specific: a passage under the same heading whose
    text no longer contains what the claim asserted and does contain what was
    proposed. Anything weaker would mark a finding applied because somebody
    happened to edit that heading.
    """
    if not finding.proposed:
        return False
    for block in document.blocks:
        if block.heading_path != claim.anchor.heading_path:
            continue
        if finding.proposed in block.text and claim.asserted not in block.text:
            return True
    return False


def _comment(
    source: PageSource,
    page_id: str,
    finding: Finding,
    claim: Claim,
    register: Register,
    result: ApplyResult,
) -> None:
    """The honest path for a passage this tool will not edit."""
    reason = claim.anchor.refusal or "this passage is outside the node allowlist"
    body = (
        f"<p><strong>runbook-reconciler</strong>: this passage no longer matches the "
        f"infrastructure it describes.</p>"
        f"<p>It says <code>{_escape(claim.asserted)}</code>; "
        f"<code>{_escape(finding.evidence_file)}</code> says "
        f"<code>{_escape(finding.observed or 'something else')}</code>.</p>"
        f"<p>This tool has not edited it, because {_escape(reason)}. "
        f"It needs a human.</p>"
    )
    source.comment(page_id, body)
    register.mark_applied(finding.finding_id)
    result.commented.append(finding.finding_id)


def _rollback(
    written: list[PagePlan], source: PageSource, register: Register, result: ApplyResult
) -> None:
    """Put back what landed before the failure. Compensating, not atomic.

    Restoring is itself a write and can itself fail. When it does the run stops
    at that page and records it as stranded, because carrying on would leave a
    batch half restored and nobody able to say which half.

    The version to write against is the one the *server* reported for our own
    write, which is what `source.write` returns and what `plan.new_version`
    holds. It used to be `plan.version + 1` — the number we assumed it would
    become. The two agree today and there is no reason to depend on that: a site
    that numbers versions differently would turn every rollback into a spurious
    conflict, and a spurious conflict here is a page left stranded that was
    perfectly restorable.

    The restoring write is itself a version this tool produced, so it goes in
    the ledger too. Otherwise the compensation is the thing the watcher sweeps
    on.
    """
    for plan in reversed(written):
        try:
            restored = source.write(
                plan.page_id, plan.original, plan.new_version or plan.version + 1
            )
            if restored:
                register.record_page_write(plan.page_id, restored)
            result.rolled_back.append(plan.page_id)
        except Exception:
            result.stranded.append(plan.page_id)
            return


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


__all__ = ["ApplyResult", "PagePlan", "PageSource", "apply_approved"]
