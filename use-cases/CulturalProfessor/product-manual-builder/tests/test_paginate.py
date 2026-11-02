"""Where the blocks land, and what happens when a translation moves one.

The localisation criterion is that translated versions keep the same page
structure. `test_localize.py` covers the half of that which is about shape --
same headings, same figures, same order. This file covers the half that is about
paper: two documents with an identical outline still print differently the moment
one is longer than the other, and that is the failure that costs a print run.

The tests that matter here are the ones where the check fires. An assertion that
has never failed is not evidence of anything, so a translation is deliberately
inflated until it moves a block, and the shift is caught and named.
"""

from __future__ import annotations

import pytest

from manualbuilder import localize as lz
from manualbuilder import paginate as pg
from manualbuilder import projections as pj

from .conftest import PROJECT_ROOT

LOCALES = ("de", "fr")


@pytest.fixture(scope="session")
def localised(spec):
    return {
        code: lz.localised_spec(spec, lz.load_locale(PROJECT_ROOT / "locales" / f"{code}.yaml"))
        for code in LOCALES
    }


# ------------------------------------------------------- the claim itself --


@pytest.mark.parametrize("code", LOCALES)
def test_every_block_of_the_manual_lands_on_the_same_page(spec, localised, code):
    source = pg.paginate(pj.manual_blocks(spec), pg.PAGE)
    translated = pg.paginate(pj.manual_blocks(localised[code]), pg.PAGE)

    assert pg.compare(source, translated) == []
    assert source.pages == translated.pages
    pg.assert_same_pagination(source, translated, code, "manual")


@pytest.mark.parametrize("code", LOCALES)
def test_every_panel_of_the_card_holds_its_step(spec, localised, code):
    """The card's creases are physical. A step that flowed across the fold in
    one language is a card that folds through a sentence."""
    source = pg.paginate(pj.quick_start_blocks(spec), pg.PANEL)
    translated = pg.paginate(pj.quick_start_blocks(localised[code]), pg.PANEL)

    assert pg.compare(source, translated) == []
    for step in spec.quick_start():
        head = translated.span(f"step:{step.id}:head")
        body = translated.span(f"step:{step.id}:body")
        assert head == body, f"{step.id} is split across the fold in {code}"


@pytest.mark.parametrize("code", LOCALES)
def test_nothing_overruns_its_page_in_any_language(spec, localised, code):
    """Stability is not enough on its own: every block landing on the same page
    is worth nothing if that page holds more than a page of content."""
    for blocks, box in ((pj.manual_blocks, pg.PAGE), (pj.quick_start_blocks, pg.PANEL)):
        assert pg.paginate(blocks(localised[code]), box).overflows() == []


@pytest.mark.parametrize("code", LOCALES)
def test_the_translation_is_actually_longer(spec, localised, code):
    """Guards the guard. If the locales were near-copies of the English, every
    assertion above would pass while proving nothing."""
    english = len(pj.manual_html(spec))
    assert len(pj.manual_html(localised[code])) > english * 1.05


# --------------------------------------------------- and when it goes wrong --


def _inflated(spec, factor: int) -> object:
    """The same spec with every step instruction repeated. A translation that
    ran long, exaggerated until it certainly moves something."""
    return lz.localised_spec(
        spec,
        {
            "language": "xx",
            "steps": {
                step.id: {"title": step.title, "body": " ".join([step.body] * factor)}
                for step in spec.steps
            },
        },
    )


def test_a_translation_that_runs_long_is_caught(spec):
    """The check has to fire. This is a locale that added no structure at all --
    same headings, same figures, same order, every word in the right place -- and
    it still cannot be printed, which is exactly why the outline check alone is
    not enough.

    Note *how* it fails. Because every step opens its own page, a long
    translation has nothing left to push down; it fills its own page past the
    bottom instead. A check that only compared page numbers would call this
    stable, and it would be right and useless."""
    source = pg.paginate(pj.manual_blocks(spec), pg.PAGE)

    # How far the design actually stretches before it breaks, measured rather
    # than asserted: every step instruction repeated until a page overruns.
    factor = next(
        f
        for f in range(2, 20)
        if pg.paginate(pj.manual_blocks(_inflated(spec, f)), pg.PAGE).overflows()
    )
    assert 4 <= factor <= 12, (
        f"the manual page absorbed {factor}x the English instruction text; if "
        f"that number moves a long way, the page model or the document changed"
    )
    overrun = pg.paginate(pj.manual_blocks(_inflated(spec, factor)), pg.PAGE)

    # Structure identical: the outline check passes this document.
    assert lz.compare_structure(pj.manual_html(spec), pj.manual_html(_inflated(spec, factor))) == []

    with pytest.raises(pg.PaginationError) as caught:
        pg.assert_same_pagination(source, overrun, "xx", "manual")
    message = str(caught.value)
    assert "does not fit" in message
    assert "step:" in message, "the message must name the block, not just a count"


def test_a_translation_that_shifts_a_block_is_caught_too(spec):
    """The other failure mode, on the stretch of document where content still
    flows: the safety notices between one declared break and the next."""
    long_warnings = lz.localised_spec(
        spec,
        {
            "language": "xx",
            "warnings": {
                w.id: {"title": w.title, "body": " ".join([w.body] * 3)} for w in spec.warnings
            },
        },
    )
    source = pg.paginate(pj.manual_blocks(spec), pg.PAGE)
    shifted = pg.paginate(pj.manual_blocks(long_warnings), pg.PAGE)

    assert pg.compare(source, shifted), "longer notices must move something"
    with pytest.raises(pg.PaginationError, match=r"does not paginate like|does not fit"):
        pg.assert_same_pagination(source, shifted, "xx", "manual")


def test_the_card_panel_is_the_thing_that_breaks_first(spec):
    """A panel is a fraction of a page, so the card is where a long translation
    shows up first. That is the document taped to the workbench, and it is the
    reason the card is checked against its own box rather than the manual's."""

    def breaks_at(blocks, box) -> int:
        for factor in range(2, 12):
            layout = pg.paginate(blocks(_inflated(spec, factor)), box)
            if layout.overflows() or pg.compare(pg.paginate(blocks(spec), box), layout):
                return factor
        return 99

    assert breaks_at(pj.quick_start_blocks, pg.PANEL) <= breaks_at(pj.manual_blocks, pg.PAGE)


def test_a_block_that_cannot_fit_any_page_is_reported_not_hidden(spec):
    """One paragraph longer than a page. It cannot be laid out correctly, and
    the honest answer is to say so rather than to place it and move on."""
    blocks = [pj.Block(id="huge", kind="p", html="<p/>", text="x" * 20_000)]
    layout = pg.paginate(blocks, pg.PAGE)
    assert layout.overflows(), "an unplaceable block must be reported"
    assert layout.overflows()[0][0] == "huge"


def test_a_long_table_is_cut_at_a_row_and_not_at_a_line(spec):
    """A table longer than the page keeps going overleaf, which is what a table
    does on paper. What must not happen is a row torn in half."""
    rows = tuple(f"row {n} " + "y" * 200 for n in range(40))
    table = pj.Block(id="big", kind="table", html="<table/>", text="head", rows=rows)
    layout = pg.paginate([table], pg.PAGE)

    parts = [p for p in layout.placements if p.block_id == "big"]
    assert len(parts) > 1, "the table should have been split"
    assert [p.rows[0] for p in parts[1:]] == [
        p.rows[1] for p in parts[:-1]
    ], "the rows must be continuous across the split, with none dropped or repeated"
    assert parts[-1].rows[1] == len(rows)


def test_two_steps_never_share_a_page(spec, localised):
    """What the declared breaks buy. A step opens a page because the spec says
    so, not because the preceding text happened to end where it did -- so no
    amount of translation can crowd two steps onto one page or split one across
    two."""
    for source in (spec, localised["de"], localised["fr"]):
        layout = pg.paginate(pj.manual_blocks(source), pg.PAGE)
        owner: dict[int, str] = {}
        for step in source.steps:
            first, last = layout.span(f"step:{step.id}:head")
            assert first == last
            assert first not in owner, f"{step.id} shares page {first} with {owner.get(first)}"
            owner[first] = step.id


def test_a_heading_never_ends_a_page(spec):
    """A section heading alone at the foot of a page is the oldest typesetting
    bug there is, and `keep_with_next` is what rules it out."""
    layout = pg.paginate(pj.manual_blocks(spec), pg.PAGE)
    by_page: dict[int, list[str]] = {}
    for placement in layout.placements:
        by_page.setdefault(placement.page, []).append(placement.block_id)

    kinds = {block.id: block.kind for block in pj.manual_blocks(spec)}
    for page, ids in by_page.items():
        assert kinds.get(ids[-1]) not in ("h1", "h2", "h3"), f"page {page} ends with a heading"


def test_the_result_depends_on_the_page_size_and_says_so(spec, localised):
    """An honest limit, pinned so nobody reads more into the green than is
    there. The claim is that these documents are stable *on this page*: 46 lines
    of 88 characters. Print the same manual on a shorter page and the German
    stops matching -- there is less room between the declared breaks, so the
    safety notices reflow. That is a true statement about paper, not a bug, and
    it is why `Box` is one dataclass in one place rather than numbers scattered
    through the renderer."""

    def shifts(lines: int) -> int:
        box = pg.Box(lines_per_page=lines)
        return len(
            pg.compare(
                pg.paginate(pj.manual_blocks(spec), box),
                pg.paginate(pj.manual_blocks(localised["de"]), box),
            )
        )

    assert shifts(46) == 0, "the shipped page size must hold"
    assert shifts(60) == 0
    assert shifts(30) > 0, "a page too short to hold the German must be reported"


def test_headroom_is_reported_so_the_next_locale_knows_what_it_has(spec, localised):
    """The number a translator needs is not "it fits", it is how much room is
    left before it stops fitting."""
    layout = pg.paginate(pj.quick_start_blocks(localised["de"]), pg.PANEL)
    panel, fill = layout.tightest()
    assert 0 < fill < 1
    assert panel in range(1, layout.pages + 1)


def test_a_step_body_is_never_orphaned_from_its_diagram(spec, localised):
    """The failure in one sentence: step six on page seven with its diagram on
    page eight. It is the concrete thing all of this is for."""
    for code in LOCALES:
        layout = pg.paginate(pj.manual_blocks(localised[code]), pg.PAGE)
        for step in spec.steps:
            assert layout.span(f"step:{step.id}:head") == layout.span(
                f"step:{step.id}:figure"
            ), f"{step.id} lost its diagram in {code}"


def test_an_unknown_block_is_a_shift_not_a_crash(spec):
    """A locale that somehow produced a block the source does not have is a
    reportable difference, not a KeyError three frames down."""
    source = pg.paginate(pj.manual_blocks(spec), pg.PAGE)
    extra = [*pj.manual_blocks(spec), pj.Block(id="stowaway", kind="p", html="<p/>", text="extra")]
    shifts = pg.compare(source, pg.paginate(extra, pg.PAGE))
    assert [s.block_id for s in shifts] == ["stowaway"]
