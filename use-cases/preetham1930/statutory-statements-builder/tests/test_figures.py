"""No figure reaches paper without a source, and no type has room for an opinion."""

from __future__ import annotations

import dataclasses
import re
from decimal import Decimal
from pathlib import Path

import pytest
from statutory import bodies, disagreement, figures
from statutory.errors import CitationDriftError, UnaccountedFigureError
from statutory.figures import (
    SOURCE_BASES,
    Body,
    Cite,
    Component,
    Derived,
    Figure,
    Gap,
    Quotient,
    assert_accounted,
)

CITE = Cite("sources/trial-balance-FY2026.csv", 200, 204, "0.00", "probe")
FORBIDDEN = (
    "resolution",
    "resolved",
    "resolve",
    "conclusion",
    "correct_value",
    "preferred_side",
    "preferred",
    "status",
    "approved",
    "verdict",
    "answer",
    "winner",
    "truth",
)


def _figure(value: str, basis: str = "ledger") -> Figure:
    return Figure("probe", Decimal(value), basis, (CITE,))


def test_an_unaccounted_token_is_a_hard_error_naming_the_token() -> None:
    with pytest.raises(UnaccountedFigureError) as caught:
        Body().markup("<p>a total of 1,234.00</p>").render("probe note")
    message = str(caught.value)
    assert "1,234.00" in message
    assert "probe note" in message
    assert "hard error rather than a warning" in message


def test_a_declared_figure_accounts_for_its_own_token() -> None:
    body = Body().markup("<p>total ").fig(_figure("1234.00")).markup("</p>")
    assert "1,234.00" in body.render("probe")


def test_two_identical_tokens_need_two_figures() -> None:
    one = _figure("5.00")
    with pytest.raises(UnaccountedFigureError):
        assert_accounted("<p>5.00 and 5.00</p>", [one], "probe")
    assert_accounted("<p>5.00 and 5.00</p>", [one, one], "probe")


def test_a_derived_total_has_no_value_field() -> None:
    names = {f.name for f in dataclasses.fields(Derived)}
    assert "value" not in names, "a stored total can drift from its citations"
    total = Derived("t", (Component(_figure("2.00")), Component(_figure("3.00"))))
    assert total.value == Decimal("5.00")
    with pytest.raises(dataclasses.FrozenInstanceError):
        total.value = Decimal("9.00")  # type: ignore[misc]


def test_a_derived_total_recomputes_from_its_components_on_every_read() -> None:
    part = _figure("2.00")
    total = Derived("t", (Component(part), Component(_figure("3.00"), -1)))
    assert total.value == Decimal("-1.00")
    assert total.cites == (CITE, CITE)
    assert total.workings() == "2.00 - 3.00 = (1.00)"


def test_a_derived_total_with_no_components_is_a_bare_number() -> None:
    with pytest.raises(ValueError, match="bare number"):
        Derived("t", ())


def test_a_figure_needs_a_basis_that_exists_and_a_citation() -> None:
    with pytest.raises(ValueError, match="not one of"):
        Figure("x", Decimal("1"), "vibes", (CITE,))
    with pytest.raises(ValueError, match="no provenance"):
        Figure("x", Decimal("1"), "ledger", ())
    assert set(SOURCE_BASES) == {"ledger", "comparative", "document"}


def test_a_quotient_divides_and_carries_both_sides_citations() -> None:
    profit = _figure("407.00")
    shares = Figure("shares", Decimal("5000000"), "document", (CITE,), literal="50,00,000")
    eps = Quotient("eps", profit, shares, Decimal(100000))
    assert eps.rendered == "8.14"
    assert len(eps.cites) == 2


def test_a_gap_that_does_not_say_where_we_looked_is_a_shrug() -> None:
    with pytest.raises(ValueError, match="shrug"):
        Gap("something is missing", ())
    assert "looked in" in Gap("x", ("the ledger",)).sentence()


def test_prose_cannot_smuggle_an_undeclared_figure() -> None:
    body = Body().markup("<p>")
    with pytest.raises(UnaccountedFigureError):
        body.prose("a difference of 9.00", ()).render("probe")


def test_a_citation_that_no_longer_reads_back_is_a_hard_error(corpus: Path) -> None:
    CITE.verify(corpus)
    with pytest.raises(CitationDriftError, match="citation drift"):
        Cite(CITE.path, CITE.byte_start, CITE.byte_end, "9.99", "probe").verify(corpus)


def test_no_outcome_type_has_a_field_an_opinion_could_be_written_into() -> None:
    """Decision 15's defence, rebuilt: the absence of a field, proved by reflection."""
    types = [
        figures.Figure,
        figures.Derived,
        figures.Component,
        figures.Gap,
        figures.Quotient,
        figures.Cite,
        disagreement.Side,
        disagreement.Disagreement,
        bodies.NoteContent,
        bodies.Element,
    ]
    for candidate in types:
        names = {f.name.lower() for f in dataclasses.fields(candidate)}
        offenders = sorted(names & set(FORBIDDEN))
        assert not offenders, f"{candidate.__name__} has {offenders}"


def test_no_assignment_to_a_resolution_name_in_the_modules_that_carry_outcomes() -> None:
    """Scoped to the outcome modules on purpose.

    A checklist item legitimately has a disclosure `status`, and an HTTP job has
    a transport `status`; neither is an opinion about which of two disagreeing
    sources is right. The rule is about the types that carry an outcome, and
    those are the three scanned here.
    """
    package = Path(figures.__file__).resolve().parent
    pattern = re.compile(rf"\b(?:{'|'.join(FORBIDDEN)})\s*=", re.I)
    hits = []
    for name in ("figures.py", "disagreement.py", "bodies.py"):
        path = package / name
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if pattern.search(stripped):
                hits.append(f"{path.name}:{number}: {stripped}")
    assert not hits, f"a resolution is being written somewhere: {hits}"
