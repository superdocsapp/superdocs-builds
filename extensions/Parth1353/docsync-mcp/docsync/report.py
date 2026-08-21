"""Rendering, in one place because two front ends show the same things.

The CLI prints these to a terminal and the MCP server returns them as tool
output for an editor to show. Keeping them here means the plan an agent sees
is the plan a person sees, word for word — which matters when the person is
deciding whether to trust what the agent just told them it was going to do.

Plain text on purpose. It renders in a terminal, in a chat panel, and in a
pull request comment without any of them needing to know about the others.
"""

from __future__ import annotations

from docsync.apply import ApplyReport
from docsync.facts import FactTable
from docsync.plan import (
    ANCHOR_UNANCHORED,
    ANCHOR_WEAK,
    AUDIT_ANCHORED,
    AUDIT_PROSE,
    AUDIT_UNRESOLVED,
    AUDIT_WEAK,
    AuditFinding,
    ChangePlan,
)
from docsync.state import Pending


def render_facts(table: FactTable) -> str:
    lines = [f"Facts as of the {table.origin}", ""]
    width = max((len(key) for key in table.values), default=10)
    for key, value in table.values.items():
        marker = "  " if value.ok else "! "
        lines.append(f"{marker}{key:<{width}}  {value.display}")
    if table.errors:
        lines += ["", f"{len(table.errors)} fact(s) could not be read. Nothing will be sent "
                      f"while that is true."]
    return "\n".join(lines)


def render_audit(findings: list[AuditFinding]) -> str:
    if not findings:
        return "No document declares coverage of any fact, so there is nothing to audit."

    by_path: dict[str, list[AuditFinding]] = {}
    for finding in findings:
        by_path.setdefault(finding.path, []).append(finding)

    symbol = {
        AUDIT_ANCHORED: "ok  ",
        AUDIT_WEAK: "WEAK",
        AUDIT_PROSE: "PROSE",
        AUDIT_UNRESOLVED: "FAIL",
    }
    lines: list[str] = []
    for path, items in by_path.items():
        lines.append(f"\n{path}")
        for item in items:
            head = f"  {symbol.get(item.status, '?'):<6} {item.key or '(document)'}"
            if item.status == AUDIT_ANCHORED:
                lines.append(f"{head}  = {item.value}  ({item.count}×)")
            else:
                lines.append(f"{head}  = {item.value or '—'}")
                if item.note:
                    lines.append(f"         {item.note}")

    counts = {status: sum(1 for f in findings if f.status == status) for status in symbol}
    lines += [
        "",
        f"{counts[AUDIT_ANCHORED]} anchored · {counts[AUDIT_WEAK]} weak · "
        f"{counts[AUDIT_PROSE]} prose-only · {counts[AUDIT_UNRESOLVED]} unresolved",
    ]
    return "\n".join(lines)


def render_plan(plan: ChangePlan, *, show_instruction: str = "") -> str:
    lines = [f"Comparing the {plan.after_origin} against the {plan.before_origin}", ""]

    if plan.unresolved:
        lines.append("BLOCKED — these could not be read, so nothing will be sent:")
        for key, why in sorted(plan.unresolved.items()):
            lines.append(f"  {key}: {why.splitlines()[0]}")
        lines.append("")

    if plan.baseline_gaps:
        lines.append(
            f"{len(plan.baseline_gaps)} fact(s) have no baseline to compare against "
            f"(new since the last sync); they are not treated as changes:"
        )
        for key in sorted(plan.baseline_gaps):
            lines.append(f"  {key}")
        lines.append("")

    if not plan.changes:
        lines.append("No tracked fact moved. Nothing to do, and nothing was spent.")
        return "\n".join(lines)

    lines.append(f"{len(plan.changes)} fact(s) moved:")
    for change in plan.changes:
        lines.append(f"  {change.label}: {change.before_display}  →  {change.after_display}")

    sending = [doc for doc in plan.documents if doc.this_round]
    held = [doc for doc in plan.documents if not doc.this_round]

    lines += ["", f"{len(sending)} document(s) to edit, {len(plan.untouched)} left alone, "
                  f"{len(plan.already_current)} already correct:"]
    def detail(doc) -> None:
        sent = {c.key for c in doc.this_round}
        for change in doc.this_round:
            anchor = doc.anchors[change.key]
            tag = {
                ANCHOR_WEAK: " [weak anchor]",
                ANCHOR_UNANCHORED: " [prose — cannot be verified]",
            }.get(anchor.kind, "")
            lines.append(
                f"          {change.label}: "
                f"{change.before_display} → {change.after_display}{tag}"
            )
        for change in doc.current:
            lines.append(f"          {change.label}: already correct")
        for change in doc.remaining:
            lines.append(
                f"          NEXT ROUND — {change.label}: "
                f"{change.before_display} → {change.after_display}"
            )
        # Held-back changes are listed for *every* document, not only for the
        # ones where nothing else is being sent. A document that gets three of
        # its four changes and silently drops the fourth is the precise shape
        # of failure this tool exists to prevent, and a report that hides it
        # behind a busy document is part of the failure rather than a record
        # of it.
        for change in doc.unanchored:
            if change.key in sent:
                continue
            lines.append(
                f"          HELD BACK — {change.label}: "
                f'"{change.before_display}" does not appear in this document, so '
                f"it cannot be changed by substitution"
            )

    for doc in sending:
        lines.append(f"  EDIT  {doc.path}")
        detail(doc)
    for doc in held:
        lines.append(f"  HELD  {doc.path}")
        detail(doc)

    for path in plan.already_current:
        lines.append(f"  DONE  {path}")
    for path in plan.untouched:
        lines.append(f"  KEEP  {path}")

    if plan.unanchored_total and not plan.allow_prose:
        lines += [
            "",
            f"  {plan.unanchored_total} change(s) held back. Pass --allow-prose to send "
            f"them as prose edits — they cannot be verified afterwards — or correct the "
            f"coverage list in the document's front matter.",
        ]

    uploads = sum(1 for doc in sending if doc.needs_upload)
    lines += [
        "",
        f"Cost of this round: {plan.operations} billable operation(s) "
        f"({uploads} upload, {len(sending)} edit). Reads, exports and approvals are free.",
    ]
    if plan.rounds > 1:
        lines.append(
            f"This takes {plan.rounds} rounds: one changed fact per document per round, "
            f"because a turn carrying two instruction items is measurably unreliable "
            f"(see the README). `docsync apply` runs them back to back."
        )
    if plan.uncovered:
        lines += [
            "",
            f"{len(plan.uncovered)} declared fact(s) are carried by no document at all: "
            + ", ".join(plan.uncovered),
        ]

    if show_instruction:
        for doc in sending:
            if doc.path == show_instruction or show_instruction == "*":
                lines += ["", f"--- instruction for {doc.path} ---", doc.instruction]
    return "\n".join(lines)


def render_pending(pending: Pending) -> str:
    if not pending.jobs:
        return "Nothing is staged."
    lines = [
        f"{pending.change_count} proposed change(s) across {len(pending.jobs)} document(s), "
        f"waiting for a decision.",
    ]
    for job in pending.jobs:
        lines.append(f"\n{job.path}")
        if job.error:
            lines.append(f"  FAILED  {job.error.splitlines()[0]}")
            continue
        for change in job.changes:
            lines.append(f"  [{change.change_id}] {change.operation}")
            if change.explanation:
                lines.append(f"      why:    {change.explanation}")
            if change.old_text:
                lines.append(f"      before: {_clip(change.old_text)}")
            lines.append(f"      after:  {_clip(change.new_text)}")
    return "\n".join(lines)


def render_report(report: ApplyReport) -> str:
    lines: list[str] = []
    for outcome in report.outcomes:
        if outcome.error:
            lines.append(f"  FAIL  {outcome.path}: {outcome.error.splitlines()[0]}")
            continue
        bits = [f"{outcome.approved} approved", f"{outcome.rejected} rejected"]
        if outcome.verified:
            bits.append(f"{len(outcome.verified)} verified")
        if outcome.not_landed:
            bits.append(f"{len(outcome.not_landed)} DID NOT LAND")
        if outcome.collateral:
            bits.append(f"{len(outcome.collateral)} COLLATERAL DAMAGE")
        if outcome.unverified:
            bits.append(f"{len(outcome.unverified)} applied but not verifiable")
        status = "FAIL" if (outcome.not_landed or outcome.collateral) else "OK  "
        lines.append(f"  {status}  {outcome.path}: {', '.join(bits)}")
        if outcome.not_landed:
            lines.append(f"          missing after the edit: {', '.join(outcome.not_landed)}")
        if outcome.collateral:
            lines.append(
                f"          a fact that was NOT meant to change is no longer correct: "
                f"{', '.join(outcome.collateral)}"
            )
        if outcome.unverified:
            lines.append(
                f"          prose edits, applied but not checkable: "
                f"{', '.join(outcome.unverified)} — read them before you commit"
            )
        if outcome.written_back:
            lines.append("          written back to the working tree")
        elif outcome.write_back_skipped:
            lines.append(f"          not written back: {outcome.write_back_skipped}")
    if report.ledger:
        lines += ["", f"  cost: {report.ledger}"]
    return "\n".join(lines)


def _clip(text: str, width: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"
