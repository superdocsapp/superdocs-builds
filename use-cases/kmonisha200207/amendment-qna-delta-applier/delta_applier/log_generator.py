"""Builds the amendment-response log: the compliance-file artifact that ties
every proposal edit back to the exact amendment/Q&A paragraph that drove it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List

from .integrity import UntouchedProof
from .models import AmendmentDelta, Confirmation, Conflict, ReviewItem, SectionImpact


def _fmt_delta(d: AmendmentDelta) -> str:
    return f"`{d.rule_type}/{d.key}`: {d.old_value!r} → {d.new_value!r} ({d.change_kind})"


def build_amendment_response_log(
    *,
    solicitation_no: str,
    deltas: List[AmendmentDelta],
    confirmations: List[Confirmation],
    conflicts: List[Conflict],
    impacts: Dict[str, SectionImpact],
    review_items: List[ReviewItem],
    untouched_proofs: Dict[str, UntouchedProof],
    generated_at: str | None = None,
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    lines: List[str] = []
    lines.append(f"# Amendment-Response Log — {solicitation_no}")
    lines.append("")
    lines.append(f"Generated: {generated_at}")
    lines.append("")

    if conflicts:
        lines.append("## ⚠ Conflicts requiring human resolution")
        lines.append("")
        lines.append("| Rule | Tracked value | Tracked source | New claim | New source |")
        lines.append("|---|---|---|---|---|")
        for c in conflicts:
            existing_src = c.existing_source.citation() if c.existing_source else "(none on record)"
            lines.append(
                f"| `{c.rule_type}/{c.key}` | {c.existing_value!r} | {existing_src} "
                f"| {c.new_value!r} | {c.new_source.citation()} |"
            )
        lines.append("")
    else:
        lines.append("## Conflicts")
        lines.append("")
        lines.append("None found. Every amendment/Q&A fact was consistent with the tracked state.")
        lines.append("")

    lines.append("## Amendment deltas applied")
    lines.append("")
    if not deltas:
        lines.append("None — no rule changes were detected in the ingested documents.")
    else:
        lines.append("| Delta | Source | Change | Affected section(s) |")
        lines.append("|---|---|---|---|")
        for d in deltas:
            affected = [
                f"{sid} ({impact.order}{' via ' + impact.caused_by_section if impact.caused_by_section else ''})"
                for sid, impact in impacts.items()
                if d in impact.deltas
            ]
            lines.append(
                f"| {d.delta_id} | {d.source.citation()} | {_fmt_delta(d)} | {', '.join(affected) or '(no proposal section mapped)'} |"
            )
    lines.append("")

    lines.append("## Staged edits and review decisions")
    lines.append("")
    if not review_items:
        lines.append("No edits were staged (no section required a change, or no run has been executed yet).")
    else:
        lines.append("| Change ID | Section | Operation | Citation(s) | Decision | Decided at |")
        lines.append("|---|---|---|---|---|---|")
        for item in review_items:
            citations = "; ".join(d.source.citation() for d in item.deltas)
            decision = "approved" if item.approved else ("rejected" if item.approved is False else "pending")
            lines.append(
                f"| {item.change_id} | {item.section_id} | {item.operation} | {citations} "
                f"| {decision} | {item.decided_at or '—'} |"
            )
    lines.append("")

    lines.append("## Confirmed unchanged (checked, no conflict)")
    lines.append("")
    if not confirmations:
        lines.append("None recorded.")
    else:
        for c in confirmations:
            lines.append(f"- `{c.rule_type}/{c.key}` confirmed unchanged by {c.source.citation()}")
    lines.append("")

    lines.append("## Untouched-section proof")
    lines.append("")
    lines.append("| Section | Verified untouched | Before hash | After hash |")
    lines.append("|---|---|---|---|")
    for section_id, proof in untouched_proofs.items():
        mark = "✅ yes" if proof.verified_untouched else "❌ NO — investigate"
        lines.append(
            f"| {section_id} | {mark} | `{(proof.before_hash or 'MISSING')[:12]}` | `{(proof.after_hash or 'MISSING')[:12]}` |"
        )
    lines.append("")

    return "\n".join(lines)
