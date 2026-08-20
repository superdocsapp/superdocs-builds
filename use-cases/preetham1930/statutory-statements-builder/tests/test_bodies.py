"""What a regenerated note may say, and what it must refuse to say."""

from __future__ import annotations

import re

from statutory.money import money_tokens, money_tokens_in_html

PRIOR_ONLY_FIGURES = {
    "312.00",  # inventories: raw materials
    "196.00",  # inventories: finished goods
    "141.00",  # cash: balances with banks
    "542.00",  # employee benefits: salaries and wages
    "4,196.00",  # revenue: sale of manufactured goods
    "68.00",  # related party: KMP remuneration
    "34.00",  # contingent: disputed GST demand
    "2,503.00",  # cost of materials: purchases
}


def test_no_regenerated_body_reuses_a_prior_year_breakdown(rolled) -> None:
    """Last year's analysis never appears under this year's heading."""
    html = rolled.document.html("target")
    tokens = set(money_tokens_in_html(html))
    reused = sorted(PRIOR_ONLY_FIGURES & tokens)
    assert not reused, f"prior-year breakdown figures reached the FY set: {reused}"


def test_the_analysis_we_cannot_reproduce_is_named_rather_than_dropped(rolled) -> None:
    gaps = [g for note in rolled.document.notes for g in note.gaps]
    assert len(gaps) >= 25
    text = " ".join(g.what for g in gaps)
    for phrase in ("Raw materials", "Salaries and wages", "Remuneration to key management"):
        assert phrase in text, f"the outstanding list should name {phrase!r}"
    for gap in gaps:
        assert any("caption granularity" in place for place in gap.looked_in)


def test_a_carried_policy_sentence_has_no_figure_and_no_period_reference(rolled) -> None:
    policies = [block for block in rolled.document.blocks if block.role.endswith("policy")]
    assert policies, "some policy prose should survive the roll-forward"
    for block in policies:
        assert not money_tokens_in_html(block.target)
        lowered = block.target.lower()
        for word in ("during the year", "for the year", "as at"):
            assert word not in lowered, f"{block.role} carries a period claim: {block.target}"


def test_the_share_capital_claim_from_last_year_is_not_carried(rolled) -> None:
    """ "There was no movement in share capital during the year" is a claim about 2025."""
    assert "no movement in share capital during the year" not in rolled.document.html("target")


def test_every_note_says_what_the_statement_says(rolled) -> None:
    assert len(rolled.caption_ties) == 29
    for tie in rolled.caption_ties:
        assert re.match(r".+ -> Note \d+: [\d,()\.]+$", tie)


def test_the_prior_year_tie_out_is_narrow_and_reports_its_own_selectivity(rolled) -> None:
    """Two groups qualified out of 25 notes; one tied, one raised."""
    assert rolled.document.coverage == {"groups": 2, "tied": 1, "raised": 1}
    tieouts = [b for b in rolled.document.blocks if b.role.endswith("comparative_tieout")]
    assert len(tieouts) == 1
    body = tieouts[0].target
    assert "821.00" in body and "812.00" in body and "9.00" in body
    assert "is not resolved" in body


def test_the_lease_note_states_the_deed_terms_and_the_ledger_balances(rolled) -> None:
    note = rolled.note(4)
    text = " ".join(e.target for e in note.elements)
    for token in ("268.00", "212.00", "62.00", "274.00", "6,50,000", "39,00,000"):
        assert token in text, token
    sources = {cite.path for figure in note.figures for cite in figure.cites}
    assert "sources/lease-agreement-warehouse-2025.md" in sources
    assert "sources/trial-balance-FY2026.csv" in sources


def test_the_business_combination_note_quotes_both_sides_and_resolves_neither(
    rolled,
) -> None:
    note = rolled.note(27)
    text = " ".join(e.target for e in note.elements)
    assert "185.00" in text
    assert "29 January 2026" in text
    assert "all 29 account names were searched and 0 matched" in text
    assert "neither is preferred" in text
    assert len(note.disagreements) == 1
    sides = note.disagreements[0].sides
    assert len(sides) == 2
    assert {s.source for s in sides} == {
        "sources/board-minutes-2026-01-18.md",
        "sources/trial-balance-FY2026.csv",
    }
    assert max(s.searched for s in sides) == 29


def test_earnings_per_share_is_computed_not_carried(rolled) -> None:
    note = rolled.note(26)
    text = " ".join(e.target for e in note.elements)
    assert "8.14" in text, "407.00 lakhs over 50,00,000 shares"
    assert "6.18" in text, "the comparative, cited to the signed set"
    assert "50,00,000" in text


def test_the_injected_instruction_has_no_channel_to_act_through(rolled) -> None:
    """Defect 4: the quarantined source is reported and then not consulted.

    The stronger half of the defence is structural: nothing in this build reads
    a satisfied-flag out of a document. A checklist item is satisfied because a
    note exists and carries the analysis, and there is no code path from source
    text to that decision.
    """
    assert rolled.quarantined == ["sources/vendor-correspondence-2026-02.md"]
    html = rolled.document.html("target")
    assert "SATISFIED" not in html
    assert "APPROVED" not in html
    assert "vendor-correspondence" not in html
    cited = {cite.path for cite in rolled.document.cites}
    assert "sources/vendor-correspondence-2026-02.md" not in cited
    # and the checklist did not become all-satisfied, which is what it asked for
    assert sum(1 for line in rolled.checklist if line.status == "satisfied") < 5


def test_a_figure_only_reaches_the_document_through_one_of_four_bases(rolled) -> None:
    bases = {f.basis for f in rolled.document.figures}
    assert bases <= {"ledger", "comparative", "document", "derived"}
    assert bases == {"ledger", "comparative", "document", "derived"}, "all four are in use"


def test_every_money_token_in_the_final_document_is_accounted_for(rolled) -> None:
    """The whole document, re-scanned, not just each body as it was built."""
    from collections import Counter

    declared = Counter(f.rendered for f in rolled.document.figures)
    found = Counter(money_tokens(_visible_text(rolled.document)))
    assert not (found - declared), f"unaccounted: {sorted((found - declared).elements())}"


def _visible_text(document) -> str:
    from statutory.money import strip_markup

    return " ".join(strip_markup(block.target) for block in document.blocks)
