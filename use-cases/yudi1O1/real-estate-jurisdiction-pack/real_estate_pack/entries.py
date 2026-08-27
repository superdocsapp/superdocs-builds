"""Stable identifiers shared across the three documents in a pack.

The pack produces a lease, a disclosure packet and a compliance index. They are
only useful if they agree with each other: the index must enumerate exactly what
the packet contains, and the lease's attachment schedule must reference exactly
those same items. Prose cannot enforce that. Identifiers can.

So every rule that fires becomes a `PackEntry` with an id assigned once — `D-1`,
`D-2`, ... for disclosures and `L-1`, `L-2`, ... for lease clauses — and all
three documents are rendered from that same numbered list. Cross-document
consistency then reduces to "were these built from one list", which
`assemble.check_consistency` verifies on the rendered output rather than trusting.

Numbering is by position in the merged rule order (federal first, then state),
which is stable for a given jurisdiction file. It is deliberately NOT derived
from a hash or from insertion order at runtime: a coordinator who regenerates a
pack after answering one more question should see the same numbers for the items
that did not change.
"""
from __future__ import annotations

from dataclasses import dataclass

from .rules import Rule


@dataclass
class PackEntry:
    """One rule that fired, with the id every document will refer to it by."""

    entry_id: str  # "D-1" | "L-3"
    rule: Rule
    stale: bool = False
    """True when the rule is past its review date and --allow-stale was used.
    Carried through to the index, which marks the row UNVERIFIED."""

    @property
    def is_disclosure(self) -> bool:
        return self.rule.kind == "disclosure"

    @property
    def title(self) -> str:
        return self.rule.title

    def citation_line(self) -> str:
        return self.rule.citation.render()


def number_entries(rules: list[Rule], stale_ids: set[str] | None = None) -> list[PackEntry]:
    """Assign D-/L- ids in rule order. `limit` rules produce no entry — a cap is
    a check, not a document, and it has already been enforced in `validate.py`."""
    stale_ids = stale_ids or set()
    entries: list[PackEntry] = []
    disclosure_n = 0
    clause_n = 0
    for rule in rules:
        if rule.kind == "disclosure":
            disclosure_n += 1
            entry_id = f"D-{disclosure_n}"
        elif rule.kind == "lease_clause":
            clause_n += 1
            entry_id = f"L-{clause_n}"
        else:
            continue
        entries.append(PackEntry(entry_id=entry_id, rule=rule, stale=rule.id in stale_ids))
    return entries


def disclosures(entries: list[PackEntry]) -> list[PackEntry]:
    return [e for e in entries if e.rule.kind == "disclosure"]


def lease_clauses(entries: list[PackEntry]) -> list[PackEntry]:
    return [e for e in entries if e.rule.kind == "lease_clause"]
