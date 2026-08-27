"""Reading commitments back out of a generated document, and judging them."""

from __future__ import annotations

from thread_to_letter.commitments import (
    FIRM,
    HEDGED,
    PROPOSED,
    SECOND_HAND,
    SUPERSEDED,
    Commitment,
    dangling_superseded,
    parse,
    summarise,
)

HEADER = ("<tr><th>Party</th><th>Owes to</th><th>Obligation</th><th>Due</th>"
          "<th>Status</th><th>Source message</th><th>Exact quote</th></tr>")


def _table(*rows: tuple[str, ...]) -> str:
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table>{HEADER}{body}</table>"


def test_a_table_becomes_commitments() -> None:
    html = _table(("Calder", "Northwind", "deliver mapping", "21 Mar", "firm", "7", "q"))
    (c,) = parse(html)
    assert c.party == "Calder" and c.due == "21 Mar" and c.status == FIRM
    assert c.source == "7"


def test_columns_may_be_renamed_or_reordered() -> None:
    """Trusting column position alone breaks the first time the model reorders them."""
    html = ("<table><tr><th>Exact quote</th><th>Who</th><th>Obligation</th></tr>"
            "<tr><td>q</td><td>Calder</td><td>deliver mapping</td></tr></table>")
    (c,) = parse(html)
    assert c.party == "Calder" and c.quote == "q"


def test_a_table_without_obligation_or_quote_is_not_a_commitments_table() -> None:
    html = "<table><tr><th>Name</th><th>Role</th></tr><tr><td>A</td><td>B</td></tr></table>"
    assert parse(html) == []


def test_an_unrecognised_status_is_never_promoted_to_firm() -> None:
    """Guessing 'firm' from a word we do not understand is how an intention becomes an
    undertaking, which is precisely the failure this build exists to avoid."""
    for raw in ("maybe", "likely", "TBC", "", "unclear"):
        (c,) = parse(_table(("A", "B", "do the thing", "", raw, "1", "q")))
        assert c.status != FIRM, f"{raw!r} was promoted to firm"


def test_status_synonyms_are_understood() -> None:
    cases = {
        "Firm": FIRM, "SUPERSEDED": SUPERSEDED, "revised": SUPERSEDED,
        "hedged intent": HEDGED, "tentative": HEDGED,
        "second-hand": SECOND_HAND, "second hand report": SECOND_HAND,
        "proposed": PROPOSED, "suggested": PROPOSED,
    }
    for raw, expected in cases.items():
        (c,) = parse(_table(("A", "B", "thing", "", raw, "1", "q")))
        assert c.status == expected, f"{raw!r} -> {c.status}"


def test_a_superseded_commitment_with_no_replacement_is_caught() -> None:
    """Observed live: the revised delivery date was dropped while the original was
    correctly marked superseded. The letter would have omitted the obligation that
    actually stands, while looking complete."""
    rows = parse(_table(
        ("Calder and Vance", "N", "deliver mapping", "14 Mar", "superseded", "5", "q"),
        ("Northwind", "C", "pay invoice", "30 days", "firm", "6", "q"),
    ))
    assert len(dangling_superseded(rows)) == 1


def test_a_superseded_commitment_with_its_replacement_is_fine() -> None:
    rows = parse(_table(
        ("Calder and Vance", "N", "deliver mapping", "14 Mar", "superseded", "5", "q"),
        ("Calder & Vance", "N", "deliver mapping", "21 Mar", "firm", "7", "q"),
    ))
    assert dangling_superseded(rows) == [], "'&' and 'and' are the same party"


def test_summary_counts_what_matters() -> None:
    rows = parse(_table(
        ("A", "B", "x", "", "firm", "1", "q"),
        ("A", "B", "y", "", "hedged", "2", "q"),
    ))
    rows[0].quote_found = True
    counts = summarise(rows)
    assert counts["firm"] == 1 and counts["hedged"] == 1
    assert counts["usable"] == 1 and counts["unverified"] == 1


def test_identical_rows_are_collapsed() -> None:
    """A model asked for a table will sometimes list one commitment twice. Two rows for
    one promise makes a reviewer check it twice and makes the counts lie."""
    from thread_to_letter.commitments import dedupe

    rows = parse(_table(
        ("Calder and Vance", "N", "schema mapping", "14 Mar", "superseded", "5", "one wording"),
        ("Calder & Vance", "N", "schema mapping", "14 Mar", "superseded", "5", "a different trim"),
    ))
    assert len(rows) == 2
    assert len(dedupe(rows)) == 1


def test_a_date_that_moved_is_two_commitments_not_one() -> None:
    """Collapsing these would hide precisely what this build exists to surface."""
    from thread_to_letter.commitments import dedupe

    rows = parse(_table(
        ("Calder", "N", "schema mapping", "14 Mar", "superseded", "5", "q1"),
        ("Calder", "N", "schema mapping", "21 Mar", "firm", "7", "q2"),
    ))
    assert len(dedupe(rows)) == 2


def test_dedupe_keeps_the_first_wording() -> None:
    from thread_to_letter.commitments import dedupe

    rows = parse(_table(
        ("A", "B", "thing", "", "firm", "1", "the fuller quote as written"),
        ("A", "B", "thing", "", "firm", "1", "a trimmed quote"),
    ))
    (kept,) = dedupe(rows)
    assert kept.quote == "the fuller quote as written"


def test_quote_marks_the_model_added_are_stripped() -> None:
    """A model wraps its quote in quote marks. Storing them means every display adds
    another pair, and the reader sees ""like this""."""
    for wrapped in ('"we will deliver"', "'we will deliver'", "“we will deliver”"):
        (c,) = parse(_table(("A", "B", "thing", "", "firm", "1", wrapped)))
        assert c.quote == "we will deliver", f"{wrapped!r} -> {c.quote!r}"


def test_quotes_inside_the_sentence_are_left_alone() -> None:
    (c,) = parse(_table(("A", "B", "thing", "", "firm", "1",
                         'he said "by Friday" and meant it')))
    assert c.quote == 'he said "by Friday" and meant it'
