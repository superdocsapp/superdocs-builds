"""The grading line, asserted.

> Run the intake for a durable financial POA and a separate healthcare POA and
> confirm the two drafts differ correctly in granted powers, and both carry the
> review notice and the external-notarisation statement.

"Differ correctly" is stronger than "differ", and it is what these tests pin
down. Three claims, each of which could be true while the other two are false:

1. each draft carries **every** power its own intake granted;
2. each draft carries **none** of the other's, and none of the powers its own
   intake withheld;
3. everything the two drafts share is shared - the successor-agent clause, both
   notices, the parties' own roles - so the difference is the powers and not an
   accident of two documents having been built differently.

These run offline against the assembled drafts. `scripts/verify_live_output.py`
asserts the same three things against the two **live** documents, read back from
the API - which is where the claim actually has to hold.
"""

from __future__ import annotations

from poa.chunks import ChunkMap, strip_markup
from poa.notices import check_notices


def test_the_two_required_drafts_are_a_durable_financial_and_a_healthcare_poa(
    financial, healthcare
) -> None:
    assert financial.poa_type == "durable"
    assert set(financial.granted) == {"financial"}
    assert set(healthcare.granted) == {"healthcare"}
    assert financial.intake_id != healthcare.intake_id


def test_each_draft_carries_every_power_its_own_intake_granted(
    financial, healthcare, library
) -> None:
    for draft in (financial, healthcare):
        text = strip_markup(draft.html("target"))
        for powers in draft.granted.values():
            assert powers, "a category with no powers would make this vacuous"
            for power_id in powers:
                power = library.powers[power_id]
                assert power.language in text, f"{draft.intake_id} is missing {power_id}"
                assert power.label in text


def test_neither_draft_carries_the_other_s_powers(financial, healthcare, library) -> None:
    """The claim the card is actually about."""
    for draft, other in ((financial, healthcare), (healthcare, financial)):
        text = strip_markup(draft.html("target"))
        strays = [
            power_id
            for powers in other.granted.values()
            for power_id in powers
            if library.powers[power_id].language in text
        ]
        assert not strays, f"{draft.intake_id} carries {strays} from {other.intake_id}"


def test_neither_draft_carries_a_power_its_own_intake_withheld(
    financial, healthcare, library
) -> None:
    """Withholding is the half that is easy to get wrong and impossible to see."""
    for draft in (financial, healthcare):
        granted = {p for powers in draft.granted.values() for p in powers}
        categories = set(draft.granted)
        withheld = [
            power_id
            for power_id, power in library.powers.items()
            if power.category in categories and power_id not in granted
        ]
        assert withheld, "if nothing were withheld this test would prove nothing"
        text = strip_markup(draft.html("target"))
        for power_id in withheld:
            assert library.powers[power_id].language not in text, (
                f"{draft.intake_id} grants {power_id}, which its intake withheld"
            )


def test_the_clause_sets_differ_by_exactly_the_healthcare_clauses(financial, healthcare) -> None:
    """The structural difference, stated exactly rather than as 'they differ'."""
    only_financial = {b.role for b in financial.blocks} - {b.role for b in healthcare.blocks}
    only_healthcare = {b.role for b in healthcare.blocks} - {b.role for b in financial.blocks}
    assert only_financial == {
        "powers-financial",
        "powers-financial-heading",
        "powers-financial-list",
    }
    assert only_healthcare == {
        "powers-healthcare",
        "powers-healthcare-heading",
        "powers-healthcare-list",
        "healthcare-records-access",
        "healthcare-records-access-heading",
    }


def test_both_drafts_carry_a_successor_agent_clause(financial, healthcare) -> None:
    for draft in (financial, healthcare):
        clause = strip_markup(draft.block("successor").target)
        assert "successor agent" in clause
        assert clause.count("successor agent") >= 1
    assert "Anjali Ramanathan" in financial.block("successor").target
    assert "Suresh Ramanathan" in healthcare.block("successor").target


def test_both_drafts_carry_both_notices_verbatim_and_the_gate_says_so(
    financial, healthcare, library
) -> None:
    """Same check the live export path runs, on the documents we computed."""
    for draft in (financial, healthcare):
        for which in ("skeleton", "target"):
            receipt = check_notices(ChunkMap(draft.html(which)), library, draft.intake_id)
            assert set(receipt.notices) == {"counsel-review", "external-execution"}
            assert "verbatim" in receipt.receipt()


def test_the_shared_parts_really_are_shared(financial, healthcare, library) -> None:
    """So the difference is the powers, not two documents built differently."""
    shared = {"preamble-principal", "nature", "successor", "signature-block"}
    for role in shared:
        assert financial.block(role).skeleton == healthcare.block(role).skeleton, role
    # The reliance clause is the one exception, and it is the right one: it
    # carries the cross-reference to the successor clause, which is numbered 6
    # in one draft and 7 in the other. It must differ in exactly that digit and
    # in nothing else - the numbering is ours and the wording is the library's.
    left = financial.block("reliance").target
    right = healthcare.block("reliance").target
    assert left != right
    assert left.replace("clause 6", "clause N") == right.replace("clause 7", "clause N")
    assert financial.block("governing-law").target == healthcare.block("governing-law").target
    # Same principal in both intakes, so this clause must be identical.
    assert (
        financial.block("preamble-principal").target
        == healthcare.block("preamble-principal").target
    )
    for notice_id in library.notices:
        assert (
            financial.block(f"{notice_id}-notice").target
            == healthcare.block(f"{notice_id}-notice").target
        )


def test_the_two_drafts_number_differently_and_both_are_internally_consistent(
    financial, healthcare
) -> None:
    assert financial.numbering != healthcare.numbering
    for draft in (financial, healthcare):
        headings = ChunkMap(draft.html("target")).headings()
        assert headings.keys() == set(draft.numbering.values())
