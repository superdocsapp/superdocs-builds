"""The note tree: where a new note goes, what everything downstream becomes.

This is the module INVARIANTS.md items 3, 4 and 5 are about, and it is the
reason there is no mid-document insertion anywhere in this build. Every
consequence of adding a note is computed **here**, before a single byte is sent:
the new note's number, the new number of every note after it, every note ->
primary cross-reference, every `Note N` in prose, and every checklist mapping.
The document is then uploaded already in that shape (Decision 29).

The insertion point is derived from the data, not from a list of note names:

    a new note triggered by an account sits immediately after the note that the
    nearest *preceding* account in the ledger already points at

For the warehouse lease that reads: account 1110 is required and unmapped; the
account before it in the ledger is 1100, which the signed balance sheet
cross-references to Note 3; therefore the lease note is Note 4 and notes 4..25
become 5..26. Nothing here knows what a lease is.

A new note triggered only by an event has no account to sit beside, so it is
appended. That is also a rule about the data, not about the standard.

The English *title* of a new note is configuration (`config/new-note-titles.csv`,
keyed on the checklist's own `standard` column). The requirement for the note is
detected; the label is a label. Recorded as an assumption rather than smuggled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from .checklist import Trigger
from .csvspans import as_records, parse_csv
from .errors import ChecklistDriftError, CrossReferenceError
from .figures import Cite
from .ledger import TrialBalance
from .priorset import NOTE_REFERENCE, PriorYearSet


@dataclass
class Note:
    key: str  # stable identity across the roll-forward
    title: str
    number: int = 0
    prior_number: int | None = None
    is_new: bool = False
    trigger_accounts: tuple[str, ...] = ()
    checklist_items: tuple[str, ...] = ()
    why: str = ""
    why_cites: tuple[Cite, ...] = ()

    @property
    def heading(self) -> str:
        return f"Note {self.number} — {self.title}"


@dataclass
class NoteTree:
    notes: list[Note]
    renumber: dict[int, int] = field(default_factory=dict)  # prior number -> final number
    account_note: dict[str, int] = field(default_factory=dict)  # account code -> final number
    inserted: list[Note] = field(default_factory=list)

    def by_number(self, number: int) -> Note:
        return next(n for n in self.notes if n.number == number)

    def by_key(self, key: str) -> Note:
        return next(n for n in self.notes if n.key == key)

    def has_number(self, number: int) -> bool:
        return any(n.number == number for n in self.notes)

    def repoint_prose(self, text: str) -> str:
        """Rewrite every `Note N` in prose through the same map that renumbered."""

        def swap(match) -> str:
            old = int(match.group(1))
            if old not in self.renumber:
                raise CrossReferenceError(
                    f"prose points at Note {old}, which the prior-year set does not have. "
                    f"Known prior notes: {sorted(self.renumber)}"
                )
            return f"Note {self.renumber[old]}"

        return NOTE_REFERENCE.sub(swap, text)


def load_new_note_titles(path: Path) -> dict[str, str]:
    _, records = as_records(parse_csv(path.read_bytes()))
    return {r["standard"].text: r["new_note_title"].text for r in records}


def build_note_tree(
    rolled,
    triggers: list[Trigger],
    new_note_titles: dict[str, str],
) -> NoteTree:
    prior = rolled.prior
    ledger = rolled.ledger
    notes: list[Note] = [
        Note(key=f"prior-{n.number}", title=n.title, prior_number=n.number) for n in prior.notes
    ]

    clusters: dict[str, list[Trigger]] = {}
    for trigger in triggers:
        if not trigger.required or trigger.item.mapped_last_year:
            continue
        standard = trigger.item.standard
        title = new_note_titles.get(standard)
        if title is None:
            raise ChecklistDriftError(
                f"item {trigger.item.item_id} ({standard}) is required and maps to no note in "
                f"the prior-year set, and no new-note title is configured for {standard!r}. "
                f"Configured: {', '.join(sorted(new_note_titles)) or '(none)'}. "
                f"A required disclosure with nowhere to live stops the run rather than "
                f"quietly vanishing from the checklist."
            )
        clusters.setdefault(title, []).append(trigger)

    # The account -> prior-note map comes from the roll-forward, which already
    # matched each ledger account to its signed-set row (and disambiguated the
    # two "Borrowings" and the two "Provisions" rows by their section). Matching
    # a second time here would be a second chance to disagree with itself.
    account_note_of_prior: dict[str, int] = {
        line.account.code: line.prior_note_ref
        for statement in rolled.statements
        for line in statement.lines
        if line.account is not None and line.prior_note_ref is not None
    }

    inserted: list[Note] = []
    for title, cluster in clusters.items():
        accounts = _trigger_accounts(cluster, ledger)
        note = Note(
            key=f"new-{title.lower().replace(' ', '-')}",
            title=title,
            is_new=True,
            trigger_accounts=accounts,
            checklist_items=tuple(t.item.item_id for t in cluster),
            why="; ".join(sorted({t.because for t in cluster})),
            why_cites=tuple(c for t in cluster for c in t.cites),
        )
        position = _insertion_index(note, notes, ledger, account_note_of_prior)
        notes.insert(position, note)
        inserted.append(note)

    for index, note in enumerate(notes, start=1):
        note.number = index

    renumber = {n.prior_number: n.number for n in notes if n.prior_number is not None}
    account_note = {
        code: renumber[number]
        for code, number in account_note_of_prior.items()
        if number in renumber
    }
    for note in inserted:
        for code in note.trigger_accounts:
            account_note[code] = note.number

    tree = NoteTree(notes=notes, renumber=renumber, account_note=account_note, inserted=inserted)
    _validate(tree, prior)
    return tree


def _trigger_accounts(cluster: list[Trigger], ledger: TrialBalance) -> tuple[str, ...]:
    codes: list[str] = []
    for trigger in cluster:
        for cite in trigger.cites:
            marker = "account "
            if marker in cite.where:
                code = cite.where.split(marker, 1)[1].split(",", 1)[0].strip()
                if ledger.has(code) and code not in codes:
                    codes.append(code)
    return tuple(sorted(codes, key=lambda c: ledger.account(c).order))


def _insertion_index(
    note: Note,
    notes: list[Note],
    ledger: TrialBalance,
    account_note_of_prior: dict[str, int],
) -> int:
    if not note.trigger_accounts:
        return len(notes)  # event-only: nothing to sit beside
    anchor = ledger.account(note.trigger_accounts[0])
    preceding = [
        a for a in ledger.accounts if a.order < anchor.order and a.code in account_note_of_prior
    ]
    following = [
        a for a in ledger.accounts if a.order > anchor.order and a.code in account_note_of_prior
    ]
    if not preceding:
        return 0
    before = account_note_of_prior[preceding[-1].code]
    if following:
        after = account_note_of_prior[following[0].code]
        if after < before:
            raise CrossReferenceError(
                f"cannot place the {note.title!r} note from the data: account "
                f"{anchor.code} sits between account {preceding[-1].code} (Note {before}) and "
                f"account {following[0].code} (Note {after}), and the notes are out of ledger "
                f"order. The insertion point is ambiguous and guessing it is exactly what "
                f"this build refuses to do."
            )
    index = next(i for i, n in enumerate(notes) if n.prior_number == before)
    while index + 1 < len(notes) and notes[index + 1].prior_number == before:
        index += 1
    return index + 1


def _validate(tree: NoteTree, prior: PriorYearSet) -> None:
    numbers = [n.number for n in tree.notes]
    if numbers != list(range(1, len(numbers) + 1)):
        raise CrossReferenceError(f"note numbers are {numbers}, which is not 1..n")
    if len(tree.renumber) != len(prior.notes):
        raise CrossReferenceError(
            f"{len(prior.notes)} prior-year notes went in and {len(tree.renumber)} came out "
            f"of the renumbering map; a note was lost."
        )
    ordered = sorted(tree.renumber.items())
    for (old_a, new_a), (old_b, new_b) in pairwise(ordered):
        if new_a >= new_b:
            raise CrossReferenceError(
                f"renumbering is not order-preserving: prior Note {old_a} -> {new_a} but prior "
                f"Note {old_b} -> {new_b}. A roll-forward may insert, never reorder."
            )
    for old, new in tree.renumber.items():
        if not tree.has_number(new):
            raise CrossReferenceError(f"prior Note {old} maps to Note {new}, which does not exist")


def remap_checklist(triggers: list[Trigger], tree: NoteTree) -> dict[str, int | None]:
    """checklist item id -> the FY2026 note that carries it, through the same map."""
    mapping: dict[str, int | None] = {}
    for trigger in triggers:
        item = trigger.item
        if item.prior_note is not None:
            if item.prior_note not in tree.renumber:
                raise ChecklistDriftError(
                    f"checklist item {item.item_id} points at prior-year Note "
                    f"{item.prior_note}, which the signed set does not have. Prior notes run "
                    f"1..{max(tree.renumber)}."
                )
            mapping[item.item_id] = tree.renumber[item.prior_note]
            continue
        carrier = next((n for n in tree.inserted if item.item_id in n.checklist_items), None)
        mapping[item.item_id] = carrier.number if carrier else None
    return mapping


def assert_checklist_consistent(
    mapping: dict[str, int | None], tree: NoteTree, headings: dict[int, str]
) -> None:
    """Every mapped item names a heading that exists, at the number we expect.

    `headings` is read back from the document, not from our own model - that is
    the point. A drift here is a hard failure, never a warning (hard rule 13's
    argument, applied to structure).
    """
    for item_id, number in sorted(mapping.items()):
        if number is None:
            continue
        if number not in headings:
            raise ChecklistDriftError(
                f"checklist item {item_id} maps to Note {number}, and the document has no "
                f"heading at that number. Headings present: {sorted(headings)}"
            )
        expected = tree.by_number(number).heading
        if headings[number] != expected:
            raise ChecklistDriftError(
                f"checklist item {item_id} maps to Note {number}; we expect the heading "
                f"{expected!r} and the document reads {headings[number]!r}"
            )
    unaccounted = sorted(set(headings) - {n.number for n in tree.notes})
    if unaccounted:
        raise ChecklistDriftError(
            f"the document carries note heading(s) {unaccounted} that our tree does not have. "
            f"An unaccounted heading is a section nobody planned - which is the shape of the "
            f"fabrication we measured on 2026-08-09."
        )
