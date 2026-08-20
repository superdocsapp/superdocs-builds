"""What the intake produced, printed so a person can check it without a browser.

The report states what was selected and what was refused. It never states that
the document is valid, executed, or fit for any purpose - the two notices say
what this product's output is, and the report does not contradict them.
"""

from __future__ import annotations

from .assemble import Draft
from .intake import Intake
from .library import Library


def render(intake: Intake, draft: Draft, library: Library, planned: int) -> str:
    lines: list[str] = []
    poa_type = library.types[intake.poa_type]
    jurisdiction = library.jurisdictions[intake.jurisdiction]

    lines.append("=" * 78)
    lines.append(f"INTAKE  {intake.intake_id}")
    lines.append("=" * 78)
    lines.append(f"  type          {poa_type.label} ({poa_type.type_id})")
    lines.append(f"  jurisdiction  {jurisdiction.label} ({jurisdiction.jurisdiction_id})")
    lines.append(f"  principal     {intake.principal.name}")
    lines.append(f"  agent         {intake.agent.name}")
    lines.append(f"  successor     {intake.successor_agent.name}")
    lines.append(f"  commences     {intake.effective_date}")
    if intake.limitation:
        lines.append(f"  limited to    {intake.limitation}")
    if intake.real_property_description:
        lines.append(f"  property      {intake.real_property_description}")

    lines.append("")
    lines.append("POWERS GRANTED (selected in the intake, worded by config/powers.csv)")
    for category in intake.categories(library):
        granted = intake.powers_in(library, category)
        withheld = [
            p
            for p, power in library.powers.items()
            if power.category == category and p not in granted
        ]
        lines.append(f"  {category}: {len(granted)} granted, {len(withheld)} withheld")
        for power_id in granted:
            lines.append(f"    + {power_id:18s} {library.powers[power_id].label}")
        for power_id in withheld:
            lines.append(f"    - {power_id:18s} {library.powers[power_id].label} (not granted)")
    ungranted = [c for c in library.category_order if c not in intake.categories(library)]
    for category in ungranted:
        lines.append(f"  {category}: no power granted, so no clause for it is in the draft")

    lines.append("")
    lines.append("CLAUSES (numbered by one pass over the selected set; nothing is asked)")
    for block in draft.blocks:
        if block.is_heading:
            lines.append(f"  {block.clause_number:2d}. {block.role[: -len('-heading')]}")

    lines.append("")
    lines.append("NOTICES (uploaded verbatim, never an edit target, re-read before any export)")
    for notice in library.notices.values():
        present = notice.text in draft.html("skeleton") and notice.text in draft.html("target")
        lines.append(f"  [{'x' if present else ' '}] {notice.notice_id}: {notice.label}")

    lines.append("")
    for receipt in draft.receipts:
        lines.append(f"  {receipt}")
    lines.append(f"  {planned} chunk replacement(s) planned")
    return "\n".join(lines)


def compare(left: Draft, right: Draft, library: Library) -> str:
    """The grading line, printed: how the two drafts differ in granted powers.

    Computed from the two drafts' own rendered text, not from the intakes that
    produced them, because the claim being made is about the documents.
    """
    lines = ["=" * 78, f"COMPARISON  {left.intake_id}  vs  {right.intake_id}", "=" * 78]
    for category in library.category_order:
        in_left = left.granted.get(category, ())
        in_right = right.granted.get(category, ())
        lines.append(
            f"  {category:15s} {left.intake_id}: {len(in_left):2d}   "
            f"{right.intake_id}: {len(in_right):2d}"
        )
    lines.append("")
    for draft, other in ((left, right), (right, left)):
        # Compared on the powers' own language, not on the category counts, so
        # this says something about the documents rather than about the intakes.
        strays = [
            library.powers[power_id].label
            for powers in other.granted.values()
            for power_id in powers
            if library.powers[power_id].language in draft.html("target")
        ]
        lines.append(
            f"  {draft.intake_id}: {len(strays)} power(s) from {other.intake_id} present "
            f"{'(THIS IS A FAILURE)' if strays else '- correct'}"
        )
    both = [
        n.notice_id
        for n in library.notices.values()
        if n.text in left.html("target") and n.text in right.html("target")
    ]
    lines.append(f"  both drafts carry, verbatim: {both}")
    return "\n".join(lines)
