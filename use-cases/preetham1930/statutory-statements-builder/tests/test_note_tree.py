"""The insertion, and everything it drags with it.

The second half of the grading line: a newly required note is detected from the
data, and note numbering plus every cross-reference stays consistent after an
insertion in the middle of the document.
"""

from __future__ import annotations

import re
import shutil
from itertools import pairwise
from pathlib import Path

import pytest
from statutory.checklist import Checklist
from statutory.errors import ChecklistDriftError, CrossReferenceError
from statutory.events import EventDetector
from statutory.ledger import TrialBalance
from statutory.notetree import (
    assert_checklist_consistent,
    build_note_tree,
    load_new_note_titles,
    remap_checklist,
)
from statutory.priorset import PriorYearSet
from statutory.statements import roll_forward

PACKAGE = Path(__file__).resolve().parent.parent / "statutory"


def test_the_lease_note_is_required_by_the_data_not_by_a_list(rolled) -> None:
    lease = next(n for n in rolled.tree.inserted if n.checklist_items[0] == "DC-025")
    assert lease.number == 4
    assert lease.trigger_accounts[0] == "1110"
    assert "1110" in lease.why and "268.00" in lease.why
    assert lease.why_cites, "the trigger must carry the ledger bytes that made it true"


def test_insertion_point_comes_from_account_order(
    corpus: Path, config: Path, tmp_path: Path
) -> None:
    """Move the right-of-use account down the ledger; the note moves with it.

    If the position were remembered rather than computed, this would still land
    the lease note at 4.
    """
    root = tmp_path / "corpus"
    shutil.copytree(corpus, root)
    ledger_path = root / "sources" / "trial-balance-FY2026.csv"
    lines = ledger_path.read_text(encoding="utf-8").splitlines(keepends=True)
    rou = next(line for line in lines if line.startswith("1110,"))
    lines.remove(rou)
    at = next(i for i, line in enumerate(lines) if line.startswith("1230,"))
    lines.insert(at + 1, rou)
    ledger_path.write_text("".join(lines), encoding="utf-8")

    tree = _tree_for(root, config)
    lease = next(n for n in tree.inserted if "DC-025" in n.checklist_items)
    assert lease.number == 9, "after the note the preceding account points at, not after PPE"
    assert tree.renumber[8] == 8 and tree.renumber[9] == 10


def test_every_prior_note_survives_and_the_order_is_preserved(rolled) -> None:
    tree = rolled.tree
    assert len(tree.renumber) == 25
    assert tree.renumber[3] == 3
    assert tree.renumber[4] == 5
    assert tree.renumber[25] == 26
    shifted = [(old, new) for old, new in tree.renumber.items() if old != new]
    assert len(shifted) == 22
    ordered = sorted(tree.renumber.items())
    assert all(a[1] < b[1] for a, b in pairwise(ordered))


def test_every_cross_reference_resolves_after_insertion(rolled) -> None:
    numbers = {note.number for note in rolled.tree.notes}
    html = rolled.document.html("target")
    referenced = {int(m.group(1)) for m in re.finditer(r"\bNote (\d+)\b", html)}
    assert referenced <= numbers
    # the one prose cross-reference in the signed set was repointed
    assert "disclosed in Note 5" in html
    assert "disclosed in Note 4" not in html


def test_the_primary_statements_point_at_the_new_numbers(rolled) -> None:
    lines = {
        line.account.code: line.note_ref
        for statement in rolled.rolled.statements
        for line in statement.lines
        if line.account is not None
    }
    assert lines["1130"] == 5, "intangibles moved from note 4 to note 5"
    assert lines["1210"] == 7
    assert lines["1110"] == 4 and lines["2210"] == 4 and lines["2310"] == 4


def test_no_note_title_is_hardcoded_in_the_package(rolled) -> None:
    """Every rolled-forward title comes from the signed set, not from our source."""
    titles = [note.title for note in rolled.tree.notes if not note.is_new]
    literals = _string_literals(PACKAGE)
    offenders = sorted({t for t in titles for lit in literals if t in lit})
    assert not offenders, f"these note titles are written into our code: {offenders}"


def test_the_checklist_is_remapped_through_the_same_map(rolled) -> None:
    mapping = rolled.mapping
    assert mapping["DC-005"] == 5, "prior note 4 -> 5"
    assert mapping["DC-007"] == mapping["DC-008"] == 7
    assert mapping["DC-024"] == 26
    assert {mapping[f"DC-0{n}"] for n in (25, 26, 27, 28)} == {4}
    assert {mapping[f"DC-0{n}"] for n in (29, 30, 31, 32)} == {27}


def test_checklist_consistency_is_asserted_against_the_document_not_our_model(
    rolled,
) -> None:
    from statutory.chunks import ChunkMap

    headings = ChunkMap(rolled.document.html("target")).headings()
    assert len(headings) == 27
    assert_checklist_consistent(rolled.mapping, rolled.tree, headings)

    drifted = dict(headings)
    drifted[5] = "Note 5 &mdash; Something else"
    with pytest.raises(ChecklistDriftError, match="DC-005"):
        assert_checklist_consistent(rolled.mapping, rolled.tree, drifted)

    extra = dict(headings)
    extra[99] = "Note 99 - Quality Assurance"
    with pytest.raises(ChecklistDriftError, match="fabrication"):
        assert_checklist_consistent(rolled.mapping, rolled.tree, extra)


def test_a_prose_reference_to_a_note_that_never_existed_raises(rolled) -> None:
    with pytest.raises(CrossReferenceError, match="Note 99"):
        rolled.tree.repoint_prose("see Note 99 for details")


def _string_literals(package: Path) -> list[str]:
    """Every string constant in our source that is not a docstring.

    Comments are excluded on purpose - a comment naming "Borrowings" to explain
    why two rows need disambiguating is documentation, not a hardcoded title.
    """
    import ast

    out: list[str] = []
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                out.append(node.value)
    return out


def _tree_for(root: Path, config: Path):
    prior = PriorYearSet(next((root / "prior-year").glob("*.html")), root)
    ledger = TrialBalance(root / "sources" / "trial-balance-FY2026.csv", root)
    forward = roll_forward(ledger, prior, root)
    events = EventDetector(config / "event-vocabulary.csv", config / "quarantine-markers.txt")
    events.scan([p for p in sorted((root / "sources").glob("*")) if p.is_file()], root)
    checklist = Checklist(root / "rules" / "disclosure-checklist-indas.csv", root)
    triggers = checklist.evaluate(ledger, events)
    tree = build_note_tree(forward, triggers, load_new_note_titles(config / "new-note-titles.csv"))
    remap_checklist(triggers, tree)
    return tree
