"""What the run says for itself, in the terminal and in a file.

Two rules shape it. Every number is computed from the objects at the moment it
is printed, never from a counter kept alongside them; and where the sources do
not support an analysis, the report says which analysis and where we looked
rather than reporting a smaller, tidier truth.
"""

from __future__ import annotations

from .money import format_money
from .pipeline import Rolled

RULE = "-" * 78


def render(rolled: Rolled, plan_size: int) -> str:
    lines: list[str] = []
    ledger = rolled.rolled.ledger
    year, prior_year = rolled.rolled.year, rolled.rolled.prior_year

    lines.append(RULE)
    lines.append(f"STATUTORY ROLL-FORWARD  FY{prior_year} -> FY{year}")
    lines.append(RULE)
    lines.append(
        f"ledger: {len(ledger)} accounts, caption granularity, columns fy{year} and fy{prior_year}"
    )
    lines.append(
        f"prior-year set: {len(rolled.rolled.prior.notes)} notes, "
        f"{len(rolled.rolled.prior.statements)} primary statements"
    )
    if rolled.quarantined:
        lines.append(
            f"quarantined and not consulted (in either direction): {', '.join(rolled.quarantined)}"
        )

    lines.append("")
    lines.append("TIES")
    for label, left, right, ok in rolled.rolled.ties:
        mark = "ok " if ok else "BAD"
        lines.append(f"  {mark} {label:58s} {format_money(left):>12s} {format_money(right):>12s}")
    matched = [c for c in rolled.rolled.comparative_checks if c.signed_value is not None]
    new_nil = [c for c in rolled.rolled.comparative_checks if c.signed_value is None]
    lines.append(
        f"  comparatives: {len(matched)} caption(s) agree between the ledger's fy{prior_year} "
        f"column and the signed set; {len(new_nil)} new caption(s) nil in both"
    )
    for check in new_nil:
        lines.append(f"      new this year: {check.caption}")
    lines.append(f"  note <-> primary cross-references checked: {len(rolled.caption_ties)}")
    coverage = rolled.document.coverage
    lines.append(
        f"  prior-year breakdown groups that qualified for a tie-out: {coverage['groups']} "
        f"({coverage['tied']} tied, {coverage['raised']} raised)"
    )

    lines.append("")
    lines.append("NOTE TREE")
    inserted = rolled.tree.inserted
    lines.append(
        f"  {len(rolled.tree.notes)} notes ({len(rolled.tree.renumber)} rolled forward, "
        f"{len(inserted)} required by this year's data)"
    )
    for note in inserted:
        lines.append(f"    + Note {note.number} {note.title}")
        lines.append(f"      required because: {note.why}")
        lines.append(f"      carries checklist items: {', '.join(note.checklist_items)}")
    shifted = [(old, new) for old, new in sorted(rolled.tree.renumber.items()) if old != new]
    if shifted:
        lines.append(
            f"    {len(shifted)} note(s) renumbered by the insertion: "
            + ", ".join(f"{old}->{new}" for old, new in shifted[:6])
            + (" ..." if len(shifted) > 6 else "")
        )

    lines.append("")
    lines.append("DISCLOSURE CHECKLIST")
    unmapped_before = [
        line for line in rolled.checklist if line.required and line.prior_note is None
    ]
    lines.append(
        f"  {len(rolled.checklist)} items evaluated from the CSV, "
        f"{sum(1 for line in rolled.checklist if line.required)} required"
    )
    lines.append(
        f"  detected from THIS YEAR'S DATA and unsatisfied in the set we rolled forward: "
        f"{len(unmapped_before)}"
    )
    for line in unmapped_before:
        lines.append(
            f"    {line.item_id}  {line.standard:10s} no note in the prior-year set "
            f"-> now Note {line.note}"
        )
        lines.append(f"        {line.requirement}")
        lines.append(f"        because: {line.because}")
    by_status: dict[str, int] = {}
    for line in rolled.checklist:
        by_status[line.status] = by_status.get(line.status, 0) + 1
    lines.append(
        "  after the roll-forward: "
        + ", ".join(f"{count} {status}" for status, count in sorted(by_status.items()))
    )
    lines.append(
        "  'outstanding' means the note exists and carries the caption, and the analysis the "
    )
    lines.append(
        "  item requires is not derivable from the sources supplied (the trial balance is at "
    )
    lines.append("  caption granularity). Each note names what is missing and where we looked.")
    lines.append("")
    lines.append("  item    standard    prior note   FY note   status")
    for line in rolled.checklist:
        prior = str(line.prior_note) if line.prior_note else "-"
        current = str(line.note) if line.note else "-"
        lines.append(
            f"  {line.item_id:7s} {line.standard:11s} {prior:>10s} {current:>9s}   {line.status}"
        )

    if rolled.disagreements:
        lines.append("")
        lines.append("SOURCES THAT DISAGREE (stated, never resolved)")
        for disagreement in rolled.disagreements:
            lines.append(f"  * {disagreement.about}")
            for side in disagreement.sides:
                extra = f" [{side.searched} location(s) searched]" if side.searched else ""
                lines.append(f"      {side.source}: {side.says}{extra}")
                lines.append(f"        cited: {len(side.cites)} byte range(s)")

    gaps = [(n.note.number, g) for n in rolled.document.notes for g in n.gaps]
    lines.append("")
    lines.append(
        f"OUTSTANDING ANALYSIS ({len(gaps)} item(s) across {len(rolled.document.notes)} notes)"
    )
    for number, gap in gaps:
        lines.append(f"  Note {number:2d}: {gap.what}")

    lines.append("")
    lines.append("DOCUMENT")
    lines.append(
        f"  {len(rolled.document.blocks)} chunk-aligned blocks; "
        f"{sum(1 for b in rolled.document.blocks if not b.editable)} are headings and are "
        f"uploaded at their final numbers (never edited)"
    )
    lines.append(
        f"  {plan_size} chunk(s) differ between the skeleton and the target -> {plan_size} single-target replacements"
    )
    lines.append(f"  {rolled.cites_verified} citation(s) re-read from the corpus bytes and matched")
    lines.append(RULE)
    return "\n".join(lines)
