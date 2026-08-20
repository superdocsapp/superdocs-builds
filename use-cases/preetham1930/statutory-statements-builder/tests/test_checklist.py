"""The rule set is data, the triggers are evaluated, and nothing fails quietly."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from statutory.checklist import Checklist
from statutory.errors import UnknownAccountError, UnknownConditionError
from statutory.events import EventDetector
from statutory.ledger import TrialBalance
from statutory.pipeline import prepare

PACKAGE = Path(__file__).resolve().parent.parent / "statutory"


def _bits(root: Path, config: Path):
    ledger = TrialBalance(root / "sources" / "trial-balance-FY2026.csv", root)
    events = EventDetector(config / "event-vocabulary.csv", config / "quarantine-markers.txt")
    events.scan([p for p in sorted((root / "sources").glob("*")) if p.is_file()], root)
    return ledger, events


def test_all_thirty_two_triggers_are_evaluated_from_the_csv(rolled) -> None:
    assert len(rolled.checklist) == 32
    assert all(line.required for line in rolled.checklist)
    assert all(line.because for line in rolled.checklist)


def test_the_eight_unmapped_items_are_detected_from_the_data(rolled) -> None:
    unmapped = [line for line in rolled.checklist if line.prior_note is None]
    assert [line.item_id for line in unmapped] == [f"DC-0{n}" for n in range(25, 33)]
    lease = [line for line in unmapped if line.item_id in {f"DC-0{n}" for n in range(25, 29)}]
    assert all("1110" in line.because or "2210" in line.because for line in lease)
    combination = [line for line in unmapped if line.item_id in ("DC-029", "DC-031")]
    assert all("board-minutes" in line.because for line in combination)


def test_the_package_never_names_an_item_id_or_a_standard() -> None:
    """The checklist is found by its columns; no *code* knows what is in it.

    `config/` may name an item id and a standard - that is what configuration
    is, and it is how a 33rd row is wired to a computation without a code edit.
    The line this test draws is between data and code, not between the repo and
    the world.
    """
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8-sig")
        assert not re.search(r"DC-\d{3}", text), f"{path.name} names a checklist item"
        assert "Ind AS" not in text, f"{path.name} names a standard"
    configured = (PACKAGE.parent / "config" / "note-recipes.csv").read_text(encoding="utf-8")
    assert re.search(r"DC-\d{3}", configured), "the wiring lives in config, and it is there"


def test_a_thirty_third_row_changes_behaviour_with_zero_code_edits(
    corpus: Path, config: Path, tmp_path: Path
) -> None:
    root = tmp_path / "corpus"
    shutil.copytree(corpus, root)
    checklist_path = root / "rules" / "disclosure-checklist-indas.csv"
    with checklist_path.open("a", encoding="utf-8") as handle:
        handle.write("DC-033,Ind AS 7,Cash flow statement,account 1220 balance > 0,7,high\n")
    result = prepare(root, config)
    line = next(line for line in result.checklist if line.item_id == "DC-033")
    assert line.required
    assert line.note == 8, "prior note 7 -> 8, through the same map as everything else"
    assert "1220" in line.because and "189.00" in line.because


def test_an_unparseable_trigger_stops_the_run_and_prints_the_grammar(
    corpus: Path, config: Path, tmp_path: Path
) -> None:
    root = tmp_path / "corpus"
    shutil.copytree(corpus, root)
    path = root / "rules" / "disclosure-checklist-indas.csv"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("DC-099,Ind AS 1,Something,when it feels right,2,high\n")
    ledger, events = _bits(root, config)
    with pytest.raises(UnknownConditionError) as caught:
        Checklist(path, root).evaluate(ledger, events)
    message = str(caught.value)
    assert "DC-099" in message and "when it feels right" in message
    assert "Grammar:" in message
    assert "not 'not required'" in message


def test_a_trigger_naming_an_account_the_ledger_lacks_stops_the_run(
    corpus: Path, config: Path, tmp_path: Path
) -> None:
    root = tmp_path / "corpus"
    shutil.copytree(corpus, root)
    path = root / "rules" / "disclosure-checklist-indas.csv"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("DC-098,Ind AS 1,Something,account 9999 balance > 0,2,high\n")
    ledger, events = _bits(root, config)
    with pytest.raises(UnknownAccountError) as caught:
        Checklist(path, root).evaluate(ledger, events)
    message = str(caught.value)
    assert "9999" in message
    assert "29 account(s)" in message
    assert "not a nil balance" in message


def test_an_event_with_no_detector_stops_the_run(
    corpus: Path, config: Path, tmp_path: Path
) -> None:
    root = tmp_path / "corpus"
    shutil.copytree(corpus, root)
    path = root / "rules" / "disclosure-checklist-indas.csv"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("DC-097,Ind AS 1,Something,a merger happened,2,high\n")
    ledger, events = _bits(root, config)
    with pytest.raises(UnknownConditionError) as caught:
        Checklist(path, root).evaluate(ledger, events)
    assert "Events defined:" in str(caught.value)


def test_an_or_condition_is_a_disjunction(corpus: Path, config: Path) -> None:
    """The lease maturity item fires because either leg is non-nil."""
    ledger, events = _bits(corpus, config)
    checklist = Checklist(corpus / "rules" / "disclosure-checklist-indas.csv", corpus)
    trigger = next(t for t in checklist.evaluate(ledger, events) if t.item.item_id == "DC-026")
    assert trigger.required
    assert "2210" in trigger.because and "2310" in trigger.because
    assert len(trigger.cites) == 2


def test_the_signed_balance_is_what_the_grammar_evaluates(corpus: Path, config: Path) -> None:
    """`balance > 0` keeps meaning 'debit balance'; no absolute value is taken."""
    ledger, _ = _bits(corpus, config)
    assert ledger.account("1110").balance(2026) > 0
    assert ledger.account("2210").balance(2026) < 0
    assert ledger.account("2210").presented(2026) > 0


def test_events_fire_on_a_block_not_on_a_document(corpus: Path, config: Path) -> None:
    """The revenue note says 'control ... transfers to the customer'; that is not a
    business combination, and requiring one block is what keeps them apart."""
    _, events = _bits(corpus, config)
    for name in events.names():
        hits = events.hits(name)
        assert len(hits) == 1
        assert hits[0].source.endswith("board-minutes-2026-01-18.md")
        assert all(cite.path == hits[0].source for cite in hits[0].cites)


def test_a_quarantined_source_can_neither_suppress_nor_manufacture_an_event(
    corpus: Path, config: Path
) -> None:
    _, events = _bits(corpus, config)
    assert [q.source for q in events.quarantined] == ["sources/vendor-correspondence-2026-02.md"]
    assert "sources/vendor-correspondence-2026-02.md" not in events.scanned
    quarantine = events.quarantined[0]
    assert quarantine.cite.read_back(corpus) == quarantine.cite.snippet
    # the forged source mentions "business combinations"; it contributed nothing
    for name in events.names():
        assert all(h.source != quarantine.source for h in events.hits(name))
