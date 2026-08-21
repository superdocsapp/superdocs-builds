"""A clause belongs to its subject, not to every subject it mentions in passing.

Found by looking at the rendered memo rather than at a passing test: the buyer's *delivery* column
was quoting warranty and title wording. Both of those clauses end with the words "from delivery"
and "on delivery", and the matcher assigned a span to every area whose keyword appeared anywhere in
it.

The result was a memo that quoted warranty text under a delivery heading — worse than useless to a
contract manager checking a supplier's position, because it looks authoritative.
"""

from __future__ import annotations

from app.domain.clause import ClauseArea, Party
from app.extraction.extractor import extract_positions
from app.extraction.patterns import areas_for, score_areas

WARRANTY_MENTIONING_DELIVERY = (
    "Goods shall be free from defects in materials and workmanship for 24 months from delivery."
)
TITLE_MENTIONING_DELIVERY = (
    "Title and risk in the goods pass to Buyer on delivery to the address stated above."
)
A_REAL_DELIVERY_CLAUSE = "Delivery shall be DDP Buyer's premises, time being of the essence."


def test_a_warranty_clause_that_mentions_delivery_is_not_a_delivery_clause() -> None:
    areas = areas_for(WARRANTY_MENTIONING_DELIVERY)

    assert ClauseArea.WARRANTY in areas
    assert ClauseArea.DELIVERY not in areas, (
        "'for 24 months from delivery' is a warranty period, not a delivery term"
    )


def test_a_title_clause_that_mentions_delivery_is_not_a_delivery_clause() -> None:
    areas = areas_for(TITLE_MENTIONING_DELIVERY)

    assert ClauseArea.TITLE_AND_RISK in areas
    assert ClauseArea.DELIVERY not in areas, (
        "'pass to Buyer on delivery' fixes when title passes; it is not a delivery obligation"
    )


def test_a_real_delivery_clause_still_matches_delivery() -> None:
    """The fix must not buy precision by refusing valid work elsewhere."""
    assert ClauseArea.DELIVERY in areas_for(A_REAL_DELIVERY_CLAUSE)


def test_position_in_the_span_is_what_separates_subject_from_reference() -> None:
    scores = score_areas(TITLE_MENTIONING_DELIVERY)

    assert scores[ClauseArea.TITLE_AND_RISK] > scores.get(ClauseArea.DELIVERY, 0), (
        "the subject is stated at the start of a clause; cross-references come later"
    )


def test_a_genuinely_dual_clause_keeps_both_areas() -> None:
    """Ties are kept, not broken arbitrarily — guessing would trade one wrong answer for another."""
    dual = "Risk of loss and shipment terms are set out in the schedule."
    areas = areas_for(dual)

    assert ClauseArea.TITLE_AND_RISK in areas
    assert ClauseArea.DELIVERY in areas


def test_a_clause_that_leans_one_way_is_assigned_that_way() -> None:
    """A documented limit, not a bug.

    Where a sentence covers two topics unevenly it goes to the dominant one rather than both.
    Splitting it would put half-relevant wording under a heading a reader trusts.
    """
    leaning = "Title and risk of loss pass to Buyer on delivery at the named place."
    assert areas_for(leaning) == {ClauseArea.TITLE_AND_RISK}


def test_the_delivery_position_no_longer_quotes_warranty_wording() -> None:
    """End to end, on the real purchase order this was found in."""
    text = "\n".join(
        [
            "12. LIABILITY",
            "Supplier's aggregate liability under this order shall be unlimited for any breach.",
            "13. DELIVERY",
            A_REAL_DELIVERY_CLAUSE,
            "15. WARRANTY",
            WARRANTY_MENTIONING_DELIVERY,
            "17. TITLE AND RISK",
            TITLE_MENTIONING_DELIVERY,
        ]
    )

    positions = extract_positions(document_id="PO.txt", text=text, party=Party.BUYER)
    delivery_quotes = " ".join(c.quote for c in positions[ClauseArea.DELIVERY].citations)

    assert "DDP" in delivery_quotes
    assert "free from defects" not in delivery_quotes, "warranty wording under a delivery heading"
    assert "Title and risk" not in delivery_quotes, "title wording under a delivery heading"

    # And the clauses that were being stolen are still found under their own areas.
    assert "free from defects" in " ".join(
        c.quote for c in positions[ClauseArea.WARRANTY].citations
    )
    assert "Title and risk" in " ".join(
        c.quote for c in positions[ClauseArea.TITLE_AND_RISK].citations
    )
