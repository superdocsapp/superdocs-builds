"""The two things this build is graded hardest on.

  1. matching **by substance rather than by heading**
  2. **silence reported as a finding distinct from a conflict**

`pile-b` exists to defeat anything tuned to `pile-a`: different parties, and none of pile A's
headings. If a change ever makes the matcher heading-dependent, pile-b is what catches it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.domain.clause import ClauseArea, Party, Verdict
from app.domain.register import reconcile
from app.extraction.extractor import extract_positions
from app.governing import EventKind, Playbook, SequenceEvent, analyse
from app.judging import HeuristicJudge
from app.letter import LetterKind, build_letter, letter_to_html
from app.memo import build_memo, memo_to_html

ROOT = Path(__file__).parents[2]
CORPUS = ROOT / "corpus"
PLAYBOOK = Playbook.from_file(ROOT / "rules" / "last-shot-england.json")


def read(pile: str, party: Party) -> tuple[str, str]:
    folder = CORPUS / pile / party.value
    path = sorted(folder.iterdir())[0]
    return path.name, path.read_text(encoding="utf-8")


def register_for(pile: str):
    buyer_name, buyer_text = read(pile, Party.BUYER)
    supplier_name, supplier_text = read(pile, Party.SUPPLIER)

    buyer = extract_positions(document_id=buyer_name, text=buyer_text, party=Party.BUYER)
    supplier = extract_positions(
        document_id=supplier_name, text=supplier_text, party=Party.SUPPLIER
    )

    judge = HeuristicJudge()
    entries = []
    unaddressed = []
    for area in ClauseArea:
        entry = reconcile(area, buyer.get(area), supplier.get(area), judge)
        (entries if entry is not None else unaddressed).append(entry if entry else area)

    return buyer_name, supplier_name, entries, unaddressed


def memo_for(pile: str):
    buyer_name, supplier_name, entries, unaddressed = register_for(pile)
    return build_memo(
        buyer_document=buyer_name,
        supplier_document=supplier_name,
        entries=entries,
        unaddressed=unaddressed,
    )


# --- silence is a finding of its own -------------------------------------------------------------


def test_silence_is_never_listed_among_conflicts() -> None:
    memo = memo_for("pile-a")

    assert memo.silences, "pile-a has clause areas the acknowledgement never mentions"
    assert all(section.verdict is Verdict.CONFLICT for section in memo.conflicts)
    assert all(section.verdict is Verdict.SILENCE for section in memo.silences)

    silent_areas = {section.area for section in memo.silences}
    conflict_areas = {section.area for section in memo.conflicts}
    assert not (silent_areas & conflict_areas), "an area cannot be both silent and contested"


def test_the_memo_gives_silence_its_own_heading_and_says_nothing_was_agreed() -> None:
    """A silence buried in a conflicts list reads as an agreement to a skimming reader."""
    html = memo_to_html(memo_for("pile-a"))

    assert "<h2>Contested points</h2>" in html
    assert "<h2>Points where one document is silent</h2>" in html
    assert "Nothing has been agreed" in html

    contested_at = html.index("<h2>Contested points</h2>")
    silent_at = html.index("<h2>Points where one document is silent</h2>")
    contested_block = html[contested_at:silent_at]
    for section in memo_for("pile-a").silences:
        assert section.heading not in contested_block, (
            f"{section.heading} is a silence but appears in the contested section"
        )


def test_a_silent_area_names_which_document_is_silent() -> None:
    memo = memo_for("pile-a")
    warranty = next(s for s in memo.silences if s.area is ClauseArea.WARRANTY)

    assert warranty.silent_party is Party.SUPPLIER
    assert "does not address it" in warranty.comment
    assert warranty.buyer_says, "the side that did speak is still quoted"
    assert not warranty.supplier_says


# --- both sides are quoted on every contested point ----------------------------------------------


def test_every_contested_point_quotes_both_sides_verbatim() -> None:
    memo = memo_for("pile-a")
    _, buyer_text = read("pile-a", Party.BUYER)
    _, supplier_text = read("pile-a", Party.SUPPLIER)

    assert memo.conflicts
    for section in memo.conflicts:
        assert section.buyer_says, f"{section.heading} quotes nothing from the buyer"
        assert section.supplier_says, f"{section.heading} quotes nothing from the supplier"
        for quote in section.buyer_says:
            assert quote in buyer_text, f"not a verbatim quote of the buyer: {quote!r}"
        for quote in section.supplier_says:
            assert quote in supplier_text, f"not a verbatim quote of the supplier: {quote!r}"


# --- matching by substance, not by heading -------------------------------------------------------


def test_pile_b_resolves_every_area_under_unfamiliar_headings() -> None:
    """pile-b shares none of pile-a's headings: "Liability Ceiling", "Forum for Disputes"."""
    _, supplier_text = read("pile-b", Party.SUPPLIER)
    assert "LIABILITY CEILING" in read("pile-b", Party.BUYER)[1].upper()
    assert "LIMITATION OF LIABILITY" not in supplier_text.upper()

    memo = memo_for("pile-b")
    covered = {s.area for s in memo.conflicts + memo.silences + memo.agreements}
    for area in (ClauseArea.LIABILITY, ClauseArea.DELIVERY, ClauseArea.PAYMENT):
        assert area in covered, f"{area} was not recognised under pile-b's headings"


def test_a_checker_that_always_finds_conflicts_would_fail_this() -> None:
    """pile-b's parties largely agree. Reporting the same shape for both piles is worthless."""
    a = memo_for("pile-a")
    b = memo_for("pile-b")

    assert len(a.conflicts) > 0
    assert len(b.conflicts) < len(a.conflicts)
    assert "contested point(s)" in a.summary_line()


# --- the letter follows from the findings --------------------------------------------------------


def test_outstanding_findings_produce_an_objection_that_reserves_rights() -> None:
    letter = build_letter(
        memo_for("pile-a"),
        to="Kessler Components GmbH",
        from_="Northwind Industrial Ltd",
        dated=date(2026, 2, 27),
        order_reference="PO-4471",
    )

    assert letter.kind is LetterKind.OBJECTION
    assert letter.preserves_position
    assert "rights are expressly reserved" in letter.reservation
    assert letter.points, "an objection with no points would concede everything"


def test_the_letter_raises_a_silence_as_a_request_not_a_retraction() -> None:
    """A contested point is objected to. A silence needs the supplier to answer."""
    memo = memo_for("pile-a")
    letter = build_letter(
        memo,
        to="Supplier",
        from_="Buyer",
        dated=date(2026, 2, 27),
        order_reference="PO-4471",
    )

    silent_headings = {s.heading for s in memo.silences}
    silent_points = [p for p in letter.points if p.heading in silent_headings]

    assert silent_points
    for point in silent_points:
        assert "does not address" in point.why_it_matters
        assert "Please confirm" in point.why_it_matters
        assert "we do not treat this point as agreed" in point.why_it_matters


def test_a_clean_comparison_produces_a_confirmation_with_no_reservation() -> None:
    from app.memo import ConflictMemo

    clean = ConflictMemo(
        buyer_document="PO.txt",
        supplier_document="ACK.txt",
        conflicts=(),
        silences=(),
        agreements=(),
        unaddressed=(),
    )
    letter = build_letter(
        clean, to="S", from_="B", dated=date(2026, 2, 27), order_reference="PO-1"
    )

    assert letter.kind is LetterKind.CONFIRMATION
    assert letter.reservation == ""
    assert "no points remain outstanding" in letter_to_html(letter)


def test_a_confirmation_is_never_produced_while_anything_is_outstanding() -> None:
    """Confirming while a conflict is open would waive the buyer's position."""
    for pile in ("pile-a", "pile-b"):
        memo = memo_for(pile)
        letter = build_letter(
            memo, to="S", from_="B", dated=date(2026, 2, 27), order_reference="PO-1"
        )
        if memo.conflicts or memo.silences:
            assert letter.kind is LetterKind.OBJECTION, (
                f"{pile} has outstanding points but produced a confirmation"
            )


# --- the memo carries the governing analysis -----------------------------------------------------


def test_the_memo_includes_the_governing_position_with_its_disclaimer() -> None:
    buyer_name, supplier_name, entries, unaddressed = register_for("pile-a")
    governing = analyse(
        [
            SequenceEvent(kind=EventKind.PO_ISSUED, on=date(2026, 2, 9), by=Party.BUYER),
            SequenceEvent(
                kind=EventKind.ACKNOWLEDGEMENT_RETURNED, on=date(2026, 2, 12), by=Party.SUPPLIER
            ),
            SequenceEvent(
                kind=EventKind.GOODS_ACCEPTED, on=date(2026, 2, 26), by=Party.BUYER
            ),
        ],
        PLAYBOOK,
    )
    memo = build_memo(
        buyer_document=buyer_name,
        supplier_document=supplier_name,
        entries=entries,
        unaddressed=unaddressed,
        governing=governing,
    )

    html = memo_to_html(memo)
    assert "Which document is likely to govern" in html
    assert "not legal advice" in html
