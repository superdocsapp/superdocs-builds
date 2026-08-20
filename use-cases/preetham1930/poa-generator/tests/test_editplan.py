"""A plan that breaks a wire rule should never reach the wire.

Everything here is checked before a single byte is sent. An invented clause in a
power of attorney is a power nobody granted, so the verb, the targets and the
post-states are all settled while it is still cheap to refuse.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from poa.assemble import CLAUSE_REFERENCE
from poa.chunks import ChunkMap, canonical, strip_markup
from poa.editplan import build_plan
from poa.errors import PlanRefusedError

CREATING_VERBS = ("create", "insert", "add a", "append", "renumber", "move ", "delete", "draft")
PACKAGE = Path(__file__).resolve().parent.parent / "poa"


def test_every_step_is_a_replacement_of_an_existing_chunk(financial, healthcare) -> None:
    for draft in (financial, healthcare):
        plan = build_plan(draft)
        assert len(plan) == 6
        uploaded = ChunkMap(_with_ids(draft.html("skeleton")))
        for step in plan.steps:
            assert step.verb == "replace"
            assert canonical(step.was_html) in {c.canonical for c in uploaded.chunks}


def test_no_step_uses_a_creating_verb(financial) -> None:
    """Decision 28: there is one verb. The instruction text is checked too."""
    plan = build_plan(financial)
    for step in plan.steps:
        step.chunk_id = "c-1"
        instruction = step.instruction()
        head = instruction.split("\n\n")[0].lower()
        assert head.startswith("replace ")
        for verb in CREATING_VERBS:
            assert f" {verb}" not in head.replace("do not add any clause", ""), verb


def test_no_step_targets_a_heading_block(financial, healthcare, limited) -> None:
    for draft in (financial, healthcare, limited):
        headings = {b.role for b in draft.blocks if b.is_heading}
        assert headings, "if there were no headings this would prove nothing"
        for step in build_plan(draft).steps:
            assert step.role not in headings
            assert step.tag not in ("h1", "h2", "h3")


def test_no_step_targets_a_notice_block(financial, healthcare, limited) -> None:
    """INVARIANTS.md B4: an instruction that touches a notice could paraphrase it."""
    for draft in (financial, healthcare, limited):
        notices = {b.role for b in draft.blocks if b.is_notice}
        assert len(notices) == 2
        for step in build_plan(draft).steps:
            assert step.role not in notices


def test_a_plan_that_named_a_notice_is_refused_before_anything_is_sent(financial) -> None:
    """The refusal is real, not merely unreachable. Drive it directly."""
    from poa.editplan import Plan, Step, assert_plan_is_legal

    notice = next(b for b in financial.blocks if b.is_notice)
    plan = Plan(
        [
            Step(
                index=1,
                role=notice.role,
                tag=notice.tag,
                clause_number=None,
                expected_html="<p>anything</p>",
                was_html=notice.skeleton,
            )
        ],
        financial,
    )
    with pytest.raises(PlanRefusedError) as exc:
        assert_plan_is_legal(plan, financial)
    assert "notice" in str(exc.value)
    assert "paraphrase" in str(exc.value)


def test_a_plan_that_named_a_heading_is_refused(financial) -> None:
    from poa.editplan import Plan, Step, assert_plan_is_legal

    heading = next(b for b in financial.blocks if b.is_heading)
    plan = Plan(
        [
            Step(
                index=1,
                role=heading.role,
                tag=heading.tag,
                clause_number=heading.clause_number,
                expected_html="<h2>99. Something</h2>",
                was_html=heading.skeleton,
            )
        ],
        financial,
    )
    with pytest.raises(PlanRefusedError, match="no renumbering step to get wrong"):
        assert_plan_is_legal(plan, financial)


def test_a_step_that_would_change_nothing_is_refused(financial) -> None:
    from poa.editplan import Plan, Step, assert_plan_is_legal

    block = financial.block("commencement")
    plan = Plan(
        [
            Step(
                index=1,
                role=block.role,
                tag=block.tag,
                clause_number=block.clause_number,
                expected_html=block.skeleton,
                was_html=block.skeleton,
            )
        ],
        financial,
    )
    with pytest.raises(PlanRefusedError, match="reads as 'not applied'"):
        assert_plan_is_legal(plan, financial)


def test_every_step_sends_a_post_state_computed_from_the_library(financial, library) -> None:
    """The instruction hands over finished bytes. It never describes an edit.

    A described edit is an invitation to draft, and drafting is what produced
    four invented sections on 2026-08-09.
    """
    plan = build_plan(financial)
    for step in plan.steps:
        step.chunk_id = "c-1"
        payload = step.instruction().split("\n\n", 1)[1]
        assert payload == step.expected_html
        assert payload == financial.block(step.role).target
    powers = next(s for s in plan.steps if s.role == "powers-financial-list")
    for power_id in financial.granted["financial"]:
        assert library.powers[power_id].language in powers.expected_html


def test_no_step_changes_a_clause_reference(financial, healthcare, limited) -> None:
    """C5. If an edit moved a number, the edit would be a renumbering."""
    for draft in (financial, healthcare, limited):
        for step in build_plan(draft).steps:
            before = CLAUSE_REFERENCE.findall(strip_markup(step.was_html))
            after = CLAUSE_REFERENCE.findall(strip_markup(step.expected_html))
            assert before == after, step.role


def test_the_riskiest_chunk_shape_is_ordered_last(financial) -> None:
    """Decision 43: a halt should lose the least verified work."""
    tags = [s.tag for s in build_plan(financial).steps]
    assert tags == sorted(tags, key=lambda t: {"p": 0, "ul": 1, "table": 2}[t])
    assert tags[-1] == "table"


def test_binding_refuses_when_a_step_matches_more_than_one_chunk(financial) -> None:
    from poa.editplan import bind_chunk_ids

    plan = build_plan(financial)
    doubled = _with_ids(financial.html("skeleton")) + "\n" + _with_ids(financial.html("skeleton"))
    with pytest.raises(PlanRefusedError, match="exactly one target"):
        bind_chunk_ids(plan, ChunkMap(doubled))


def test_binding_matches_on_content_not_on_position(financial) -> None:
    """A document that came back re-ordered fails here, not silently mid-run."""
    from poa.editplan import bind_chunk_ids

    plan = build_plan(financial)
    blocks = _with_ids(financial.html("skeleton")).split("\n")
    uploaded = ChunkMap("\n".join(reversed(blocks)))
    bind_chunk_ids(plan, uploaded)
    for step in plan.steps:
        assert uploaded.by_id[step.chunk_id].canonical == canonical(step.was_html)


def test_the_package_never_asks_the_product_to_create(financial) -> None:
    """Grep our own source for a creating verb inside an instruction we send."""
    text = (PACKAGE / "editplan.py").read_text(encoding="utf-8-sig")
    body = text.split("def instruction")[1].split("def describe")[0]
    sent = re.findall(r'f?"([^"]*)"', body)
    joined = " ".join(sent).lower()
    assert "replace the entire contents" in joined
    for verb in ("create ", "insert ", "append ", "renumber "):
        assert verb not in joined, verb


def _with_ids(html: str) -> str:
    out = []
    for index, line in enumerate(html.split("\n")):
        out.append(re.sub(r"<([a-zA-Z0-9]+)", rf'<\1 data-chunk-id="c-{index}"', line, count=1))
    return "\n".join(out)
