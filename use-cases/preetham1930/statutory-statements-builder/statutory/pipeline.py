"""One function that turns `corpus/` into the document we intend to end up with.

Everything before this point is ours and nothing here touches the network. The
whole roll-forward - parse, tie, detect, renumber, repoint, regenerate, render -
runs offline against the corpus, which is why the test suite can exercise real
behaviour with no API key (hard rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .bodies import NoteContent
from .checklist import Checklist, Trigger
from .events import EventDetector
from .figures import verify_all
from .ledger import TrialBalance
from .notetree import NoteTree, build_note_tree, load_new_note_titles, remap_checklist
from .priorset import PriorYearSet
from .skeleton import StatutoryDocument, assert_note_captions_tie, build_document
from .statements import RollForward, roll_forward

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config"


@dataclass
class ChecklistLine:
    item_id: str
    standard: str
    requirement: str
    required: bool
    because: str
    prior_note: int | None
    note: int | None
    status: str  # satisfied | outstanding | unsatisfied | not required

    @property
    def flagged(self) -> str:
        return "" if self.status == "satisfied" else self.status


@dataclass
class Rolled:
    rolled: RollForward
    tree: NoteTree
    document: StatutoryDocument
    triggers: list[Trigger]
    mapping: dict[str, int | None]
    checklist: list[ChecklistLine] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    caption_ties: list[str] = field(default_factory=list)
    cites_verified: int = 0

    @property
    def unsatisfied(self) -> list[ChecklistLine]:
        return [line for line in self.checklist if line.status != "satisfied"]

    @property
    def disagreements(self) -> list:
        return [d for note in self.document.notes for d in note.disagreements]

    def note(self, number: int) -> NoteContent:
        return next(n for n in self.document.notes if n.note.number == number)


def prepare(corpus_root: Path, config_root: Path = DEFAULT_CONFIG) -> Rolled:
    prior = PriorYearSet(
        next((corpus_root / "prior-year").glob("*.html")),
        corpus_root,
    )
    ledger = TrialBalance(_find_ledger(corpus_root), corpus_root)
    rolled = roll_forward(ledger, prior, corpus_root)

    events = EventDetector(
        config_root / "event-vocabulary.csv", config_root / "quarantine-markers.txt"
    )
    events.scan(
        [p for p in sorted((corpus_root / "sources").glob("*")) if p.is_file()], corpus_root
    )

    checklist = Checklist(_find_checklist(corpus_root), corpus_root)
    triggers = checklist.evaluate(ledger, events)

    tree = build_note_tree(
        rolled, triggers, load_new_note_titles(config_root / "new-note-titles.csv")
    )
    mapping = remap_checklist(triggers, tree)

    # The primary statements' cross-references are repointed through the same
    # map that renumbered the headings. This is the only place a note reference
    # is written onto a statement line, so there is one map and no second chance
    # to disagree with itself.
    for statement in rolled.statements:
        for line in statement.lines:
            if line.account is not None:
                line.note_ref = tree.account_note.get(line.account.code)

    document = build_document(rolled, tree, mapping, corpus_root, config_root)

    out = Rolled(rolled, tree, document, triggers, mapping)
    out.quarantined = [q.source for q in events.quarantined]
    out.caption_ties = assert_note_captions_tie(document, rolled)
    out.checklist = _score_checklist(triggers, mapping, document)
    out.cites_verified = verify_all(document.figures, corpus_root)
    for cite in document.cites:
        cite.verify(corpus_root)
    return out


def _score_checklist(
    triggers: list[Trigger], mapping: dict[str, int | None], document: StatutoryDocument
) -> list[ChecklistLine]:
    blocked: dict[int, set[str]] = {}
    gapped: set[int] = set()
    for note in document.notes:
        blocked.setdefault(note.note.number, set()).update(note.blocked_items)
        if note.gaps or note.disagreements:
            gapped.add(note.note.number)
    lines: list[ChecklistLine] = []
    for trigger in triggers:
        item = trigger.item
        number = mapping.get(item.item_id)
        if not trigger.required:
            status = "not required"
        elif number is None:
            status = "unsatisfied"
        elif item.item_id in blocked.get(number, set()) or number in gapped:
            status = "outstanding"
        else:
            status = "satisfied"
        lines.append(
            ChecklistLine(
                item_id=item.item_id,
                standard=item.standard,
                requirement=item.requirement,
                required=trigger.required,
                because=trigger.because,
                prior_note=item.prior_note,
                note=number,
                status=status,
            )
        )
    return lines


def _find_ledger(corpus_root: Path) -> Path:
    """Found by its columns, not its filename."""
    for path in sorted((corpus_root / "sources").glob("*.csv")):
        header = path.read_bytes().split(b"\n", 1)[0].decode("utf-8")
        if "account_code" in header and "statement" in header:
            return path
    raise FileNotFoundError(
        f"no trial balance in {corpus_root / 'sources'}: a trial balance is a CSV whose header "
        f"carries account_code and statement columns"
    )


def _find_checklist(corpus_root: Path) -> Path:
    for path in sorted((corpus_root / "rules").glob("*.csv")):
        header = path.read_bytes().split(b"\n", 1)[0].decode("utf-8")
        if "trigger_condition" in header and "satisfied_by_note" in header:
            return path
    raise FileNotFoundError(
        f"no disclosure checklist in {corpus_root / 'rules'}: a checklist is a CSV whose header "
        f"carries trigger_condition and satisfied_by_note columns"
    )
