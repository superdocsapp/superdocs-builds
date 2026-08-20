"""Structure is ours: clause selection, numbering, cross-references, both fills.

The claim these tests defend is that nothing structural is ever asked of
SuperDocs. The way to break that claim is not to send a bad instruction - it is
to compute the structure wrong and then send perfectly good instructions.
"""

from __future__ import annotations

import shutil

import pytest
from poa.assemble import CLAUSE_REFERENCE, assemble
from poa.chunks import ChunkMap, strip_markup
from poa.errors import CrossReferenceError
from poa.intake import load_intake
from poa.library import Library


def test_clause_numbers_come_from_the_selected_set(financial, healthcare) -> None:
    """The two required drafts number differently, and nothing was asked for it.

    The healthcare draft selects `healthcare-records-access`, which the
    financial one does not, so every clause after it is numbered one higher.
    """
    assert financial.numbering["successor"] == 6
    assert healthcare.numbering["successor"] == 7
    assert "healthcare-records-access" not in financial.numbering
    assert healthcare.numbering["healthcare-records-access"] == 6

    for draft in (financial, healthcare):
        numbers = list(draft.numbering.values())
        assert numbers == list(range(1, len(numbers) + 1)), "one pass, contiguous, from 1"


def test_every_cross_reference_resolves_in_both_drafts(financial, healthcare, limited) -> None:
    for draft in (financial, healthcare, limited):
        numbers = set(draft.numbering.values())
        found = 0
        for block in draft.blocks:
            if block.is_heading:
                continue
            for match in CLAUSE_REFERENCE.finditer(strip_markup(block.target)):
                found += 1
                assert int(match.group(1)) in numbers
        assert found >= 1, f"{draft.intake_id} has no cross-reference, so this proves nothing"


def test_the_cross_reference_actually_points_at_the_right_clause(financial, healthcare) -> None:
    """Not just 'a clause that exists' - the successor clause specifically."""
    for draft in (financial, healthcare):
        reliance = draft.block("reliance").target
        referenced = int(CLAUSE_REFERENCE.search(strip_markup(reliance)).group(1))
        assert referenced == draft.numbering["successor"]
        heading = draft.block("successor-heading").target
        assert strip_markup(heading).startswith(f"{referenced}.")


def test_the_numbering_in_the_headings_is_what_the_document_carries(financial) -> None:
    """Read back off the rendered HTML with the same parser the verifier uses."""
    headings = ChunkMap(financial.html("target")).headings()
    assert headings.keys() == set(financial.numbering.values())
    assert headings[1].endswith("Principal")
    assert headings[max(headings)].startswith(f"{max(headings)}. ")


def test_the_blank_form_and_the_filled_draft_have_the_same_structure(
    financial, healthcare, limited
) -> None:
    """The skeleton is what gets uploaded, so it must already be the final shape."""
    for draft in (financial, healthcare, limited):
        blank = ChunkMap(draft.html("skeleton"))
        filled = ChunkMap(draft.html("target"))
        assert len(blank) == len(filled), "an edit never adds or removes a chunk"
        assert [c.tag for c in blank.chunks] == [c.tag for c in filled.chunks]
        assert blank.headings() == filled.headings(), "no edit ever renumbers anything"


def test_a_heading_is_never_different_between_the_two_fills(financial, healthcare, limited) -> None:
    for draft in (financial, healthcare, limited):
        for block in draft.blocks:
            if block.is_heading:
                assert not block.changed, f"{block.role} would become a renumbering instruction"


def test_the_limited_type_carries_its_limitation_and_the_others_have_no_such_clause(
    financial, healthcare, limited
) -> None:
    assert "limitation" in {b.role for b in limited.blocks}
    assert "limitation" not in {b.role for b in financial.blocks}
    assert "limitation" not in {b.role for b in healthcare.blocks}
    assert "letting, upkeep and registration" in limited.block("limitation").target
    assert "Limited power of attorney" in limited.block("title").target
    assert "Durable power of attorney" in financial.block("title").target


def test_the_type_language_differs_across_all_three_types(library, intakes, tmp_path) -> None:
    """general / limited / durable is the distinction the card says people need right."""
    root = tmp_path / "config"
    shutil.copytree(library.root, root)
    updated = Library(root)
    languages = set()
    for type_id in ("general", "limited", "durable"):
        raw = (intakes / "limited-real-property.json").read_text(encoding="utf-8")
        raw = raw.replace('"poa_type": "limited"', f'"poa_type": "{type_id}"')
        if type_id != "limited":
            raw = raw.replace(
                '"limitation": "the letting, upkeep and registration of the real property '
                'described in this instrument, and the payment of outgoings on it"',
                '"limitation": null',
            )
        path = tmp_path / f"{type_id}.json"
        path.write_text(raw, encoding="utf-8")
        draft = assemble(load_intake(path, updated), updated)
        languages.add(draft.block("nature").target)
    assert len(languages) == 3, "each type states its own durability language"


def test_a_reference_that_moves_between_the_fills_is_refused(library, intakes, tmp_path) -> None:
    """C5: filling in a name may not move a clause number, ever."""
    root = tmp_path / "config"
    shutil.copytree(library.root, root)
    path = root / "clause-library.csv"
    # A body that renders a different clause number depending on the fill would
    # make an edit into a renumbering instruction.
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "A successor agent appointed under clause {clause_ref:successor} is subject to the "
            "same condition.",
            "A successor agent appointed under clause {clause_ref:successor} is subject to the "
            "same condition. See also clause {effective_date}.",
            1,
        ),
        encoding="utf-8",
    )
    updated = Library(root)
    intake = load_intake(intakes / "durable-financial.json", updated)
    object.__setattr__(intake, "effective_date", "3")
    with pytest.raises(CrossReferenceError, match="renumbering instruction"):
        assemble(intake, updated)


def test_the_powers_language_is_the_catalogue_s_word_for_word(financial, library) -> None:
    """The granted-powers language is determined by the intake, not written per case."""
    rendered = financial.block("powers-financial-list").target
    for power_id in financial.granted["financial"]:
        power = library.powers[power_id]
        assert power.language in rendered
        assert f"<strong>{power.label}.</strong>" in rendered
    withheld = [
        p
        for p, v in library.powers.items()
        if v.category == "financial" and p not in financial.granted["financial"]
    ]
    assert withheld, "if nothing were withheld this would prove nothing"
    for power_id in withheld:
        assert library.powers[power_id].language not in financial.html("target")


def test_the_blank_form_names_no_party_and_grants_no_specific_power(financial, library) -> None:
    """What is uploaded is a blank form. It must not carry the intake's answers."""
    blank = financial.html("skeleton")
    assert "Kavitha Ramanathan" not in blank
    assert "Suresh Ramanathan" not in blank
    assert "Anjali Ramanathan" not in blank
    for power_id in financial.granted["financial"]:
        assert library.powers[power_id].language not in blank
    # ... and it is recognisably a durable POA form for this jurisdiction, which
    # is what makes uploading it verbatim honest rather than a trick.
    assert "Durable power of attorney" in blank
    assert "Telangana, India" in blank
    assert library.notices["counsel-review"].text in blank


def test_a_clause_body_appears_exactly_once_per_draft(financial, healthcare, limited) -> None:
    """A duplicated clause is the 2026-08-09 failure; here it would duplicate a power."""
    for draft in (financial, healthcare, limited):
        roles = [b.role for b in draft.blocks]
        assert len(roles) == len(set(roles))
