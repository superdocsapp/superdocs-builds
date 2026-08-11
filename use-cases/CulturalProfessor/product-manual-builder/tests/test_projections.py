"""The card cannot contradict the manual, and the test says why not.

The first grading criterion is that the quick-start stays consistent when the
manual changes. The mechanism is that neither document contains anything: both
are rendered from the spec. These tests check the property that mechanism is
supposed to buy, rather than checking that the mechanism exists.
"""
from __future__ import annotations

import re

from manualbuilder import projections as pj


def test_every_instruction_on_the_card_is_in_the_manual(spec):
    """Word for word. If the card ever said "1.2 N·m" where the manual said
    "1.4 N·m", someone would tighten the wrong screw -- and that divergence is
    exactly what a hand-maintained pair of documents produces after one edit."""
    manual = pj.manual_html(spec)
    card = pj.quick_start_html(spec)

    for step in spec.quick_start():
        assert step.body in card
        assert step.body in manual


def test_every_warning_on_the_card_is_worded_as_the_manual_words_it(spec):
    manual = pj.manual_html(spec)
    card = pj.quick_start_html(spec)

    for warning_id in spec.quick_start_warnings:
        warning = spec.warning(warning_id)
        assert warning.body in card
        assert warning.body in manual


def test_the_card_is_a_subset_and_says_so_in_its_own_numbering(spec):
    """The card carries six of seven steps. Numbering them by their manual
    position would print a sequence with a hole in it; numbering them by their
    position on the card is right, and is why the headings differ while every
    instruction does not."""
    card = pj.quick_start_html(spec)
    headings = re.findall(r"<h3[^>]*>(\d+)\. ", card)
    assert headings == [str(n) for n in range(1, len(spec.quick_start_steps) + 1)]
    assert len(spec.quick_start_steps) < len(spec.steps)


def test_a_spec_change_moves_both_documents(spec, tmp_path):
    """The actual claim. One edit to the source, and the figure changes in both
    places -- because there is only one place it lives."""
    import yaml

    from manualbuilder.spec import load_spec

    from .conftest import SPEC_PATH

    raw = yaml.safe_load(SPEC_PATH.read_text())
    for step in raw["setup_steps"]:
        if step["id"] == "rails":
            step["body"] = step["body"].replace("1.2 N·m", "1.6 N·m")
    path = tmp_path / "retorqued.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))

    edited = load_spec(path)
    rails = edited.step("rails")
    assert "1.6 N·m" in rails.body

    # The edited sentence, verbatim, in both documents -- and the pre-edit
    # sentence in neither. Asserting on "1.2 N·m" alone would fail here for an
    # uninteresting reason: the gantry step legitimately still says 1.2, because
    # only the rails torque changed.
    for rendered in (pj.manual_html(edited), pj.quick_start_html(edited)):
        assert rails.body in rendered
        assert spec.step("rails").body not in rendered


def test_the_manual_carries_every_step_and_every_warning(spec):
    """The card is allowed to be a subset. The manual is not."""
    manual = pj.manual_html(spec)
    for step in spec.steps:
        assert step.title in manual
        assert step.body in manual
    for warning in spec.warnings:
        assert warning.body in manual
    for fault in spec.faults:
        assert fault.symptom in manual and fault.fix in manual
    for statement in spec.statements:
        assert statement.title in manual and statement.body in manual


def test_the_cards_fixes_are_the_manuals_fixes(spec):
    """The same failure as a diverging torque figure, one section further down:
    the card says power-cycle and the manual says re-seat the magnet, and the
    person at the bench believes the card. Three of the six rows ride along, and
    they are the manual's rows rendered twice rather than a shorter re-wording."""
    manual = pj.manual_html(spec)
    card = pj.quick_start_html(spec)

    assert len(spec.quick_start_faults) < len(spec.faults)
    for fault in spec.quick_start_troubleshooting():
        assert fault.symptom in card and fault.symptom in manual
        assert fault.fix in card and fault.fix in manual
    # And the rows the card left behind stayed behind.
    for fault in spec.faults:
        if fault.id not in spec.quick_start_faults:
            assert fault.fix not in card


def test_the_card_does_not_carry_the_legal_statements(spec):
    """A deliberate asymmetry, stated so it is a decision rather than an
    oversight: the warranty and the WEEE text belong in the manual, and a folded
    card that reproduced them would be a card nobody reads. The card points at
    the manual in its footer instead."""
    card = pj.quick_start_html(spec)
    for statement in spec.statements:
        assert statement.body not in card
    assert spec.quick_start_footer in card


def test_every_block_id_appears_once_in_the_rendered_html(spec):
    """The page map is keyed by block id, so a block whose id never reached the
    markup would be measured and not printed -- or printed twice and measured
    once. Either way the pagination check would be describing a document that
    does not exist."""
    for blocks, html in ((pj.manual_blocks(spec), pj.manual_html(spec)),
                         (pj.quick_start_blocks(spec), pj.quick_start_html(spec))):
        ids = [block.id for block in blocks]
        assert len(ids) == len(set(ids)), "block ids must be unique in a document"
        for block_id in ids:
            assert html.count(f'data-block="{block_id}"') == 1

        # ...and in the same order, because the layout walks them in order.
        found = re.findall(r'data-block="([^"]+)"', html)
        assert found == ids


def test_diagrams_render_as_captioned_figures_with_no_urls_yet(spec):
    """Rendering with no images is legal, and is what makes the HTML testable
    with no network. The caption carries the figure either way."""
    manual = pj.manual_html(spec)
    assert "<img" not in manual
    assert manual.count("<figcaption>") == len(pj.image_ids(spec))
    for image_id in pj.image_ids(spec):
        assert f'data-diagram="{image_id}"' in manual


def test_diagram_urls_are_substituted_when_supplied(spec):
    images = {image_id: f"https://cdn.example/{image_id}.svg"
              for image_id in pj.image_ids(spec)}
    manual = pj.manual_html(spec, images)
    assert manual.count("<img ") == len(images)
    assert "https://cdn.example/step:laser.svg" in manual


def test_markup_is_escaped(spec, tmp_path):
    """A product name is data, and a document service parses this into chunks."""
    import yaml

    from manualbuilder.spec import load_spec

    from .conftest import SPEC_PATH

    raw = yaml.safe_load(SPEC_PATH.read_text())
    raw["product"]["name"] = 'Halyard <script>alert("x")</script>'
    path = tmp_path / "hostile.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))

    hostile = load_spec(path)
    manual = pj.manual_html(hostile)
    assert "<script>" not in manual
    assert "&lt;script&gt;" in manual


def test_the_two_documents_do_not_hold_the_same_figures(spec):
    """The fact the diagram swap has to know. The manual carries the breakdown
    and a diagram per step; the card carries the breakdown alone, captioned
    differently because it has no parts table to point at. Handing the card the
    manual's list of substitutions is what made it refuse the lot."""
    manual = pj.captions_in(pj.manual_blocks(spec))
    card = pj.captions_in(pj.quick_start_blocks(spec))

    assert len(manual) == 1 + len(spec.steps)
    assert card == {f"{spec.name} parts breakdown": pj.BREAKDOWN}
    assert not set(card) & set(manual), "the two spellings must stay distinct"
    # Both spellings resolve to the same drawing, and the union is what the
    # check on the way back looks a returned caption up in.
    assert pj.captions(spec) == manual | card
