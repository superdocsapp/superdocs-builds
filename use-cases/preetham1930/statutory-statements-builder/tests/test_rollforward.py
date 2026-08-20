"""The comparatives tie exactly, and a disagreement stops the run.

This is the first half of the grading line. It is checked twice: caption by
caption against the signed set, and total by total, because a set can agree row
by row and still print a wrong total.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from statutory.errors import ComparativeMismatchError, TieBreakError
from statutory.figures import Figure
from statutory.ledger import TrialBalance
from statutory.pipeline import prepare
from statutory.priorset import PriorYearSet
from statutory.statements import roll_forward


def _copy_corpus(corpus: Path, tmp_path: Path) -> Path:
    destination = tmp_path / "corpus"
    shutil.copytree(corpus, destination)
    return destination


def test_the_four_ties_in_the_task_hold(rolled) -> None:
    document = rolled.rolled
    assert document.total("TOTAL ASSETS").value == Decimal("4857.00")
    assert document.total("TOTAL EQUITY AND LIABILITIES").value == Decimal("4857.00")
    assert document.prior_total("TOTAL ASSETS").value == Decimal("4068.00")
    assert document.prior_total("TOTAL EQUITY AND LIABILITIES").value == Decimal("4068.00")

    profit_and_loss = document.statement("profit_and_loss")
    assert profit_and_loss.line("Profit before tax").current.value == Decimal("577.00")
    assert profit_and_loss.line("Profit before tax").prior.value == Decimal("414.50")
    assert profit_and_loss.line("Profit for the year").current.value == Decimal("407.00")
    assert profit_and_loss.line("Profit for the year").prior.value == Decimal("309.00")

    other_equity = document.caption_line("2110")
    assert other_equity.prior.value + Decimal("407.00") == other_equity.current.value
    assert other_equity.current.value == Decimal("1691.00")
    assert all(ok for _, _, _, ok in document.ties)


def test_every_total_the_signed_set_prints_is_reproduced(rolled) -> None:
    labels = [label for label, _, _, _ in rolled.rolled.ties]
    assert sum(1 for label in labels if "vs signed set" in label) >= 11


def test_a_comparative_is_cited_twice_or_it_is_not_a_comparative(rolled) -> None:
    comparatives = [
        line.prior
        for statement in rolled.rolled.statements
        for line in statement.lines
        if line.account is not None and isinstance(line.prior, Figure)
    ]
    assert comparatives
    for figure in comparatives:
        if figure.basis == "comparative":
            assert len(figure.cites) == 2
            paths = {cite.path for cite in figure.cites}
            assert len(paths) == 2, "one cite to the ledger, one to the signed set"

    with pytest.raises(ValueError, match="cited twice"):
        Figure("x", Decimal("1.00"), "comparative", (comparatives[0].cites[0],))


def test_a_comparative_mismatch_is_a_hard_error(corpus: Path, tmp_path: Path) -> None:
    """Doctor the ledger's prior-year column; the signed set now disagrees."""
    root = _copy_corpus(corpus, tmp_path)
    ledger_path = root / "sources" / "trial-balance-FY2026.csv"
    raw = ledger_path.read_text(encoding="utf-8")
    ledger_path.write_text(
        raw.replace(
            "1210,Trade receivables,BS,Current assets,812.00",
            "1210,Trade receivables,BS,Current assets,800.00",
        ),
        encoding="utf-8",
    )
    prior = PriorYearSet(next((root / "prior-year").glob("*.html")), root)
    ledger = TrialBalance(ledger_path, root)
    with pytest.raises(ComparativeMismatchError) as caught:
        roll_forward(ledger, prior, root)
    message = str(caught.value)
    assert "Trade receivables" in message
    assert "800.00" in message and "812.00" in message
    assert "bytes" in message, "the error must say where to look, not only that it failed"


def test_a_balance_sheet_that_does_not_balance_stops_the_run(corpus: Path, tmp_path: Path) -> None:
    root = _copy_corpus(corpus, tmp_path)
    ledger_path = root / "sources" / "trial-balance-FY2026.csv"
    raw = ledger_path.read_text(encoding="utf-8")
    ledger_path.write_text(
        raw.replace(
            ",1200,Inventories,BS,Current assets,685.00,747.00",
            ",1200,Inventories,BS,Current assets,685.00,777.00",
        ).replace(
            "1200,Inventories,BS,Current assets,685.00,747.00",
            "1200,Inventories,BS,Current assets,685.00,777.00",
        ),
        encoding="utf-8",
    )
    prior = PriorYearSet(next((root / "prior-year").glob("*.html")), root)
    with pytest.raises(TieBreakError, match="does not balance"):
        roll_forward(TrialBalance(ledger_path, root), prior, root)


def test_new_captions_are_nil_in_the_prior_year_and_absent_from_the_signed_set(
    rolled,
) -> None:
    new = [c for c in rolled.rolled.comparative_checks if c.signed_value is None]
    assert {c.caption for c in new} == {
        "Right-of-use assets",
        "Lease liabilities - non-current",
        "Lease liabilities - current",
    }
    assert all(c.ledger_value == 0 for c in new)


def test_the_whole_roll_forward_runs_with_no_key_and_no_network(
    corpus: Path, config: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    result = prepare(corpus, config)
    assert result.cites_verified > 400
    assert len(result.document.blocks) > 90
