"""One verb, no heading, one chunk. Checked before anything reaches the wire."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from statutory.chunks import ChunkMap
from statutory.editplan import (
    Step,
    assert_plan_is_legal,
    bind_chunk_ids,
    build_plan,
    expected_after,
)
from statutory.errors import PlanRefusedError

PACKAGE = Path(__file__).resolve().parent.parent / "statutory"


def test_every_step_is_a_replacement_of_an_existing_chunk(rolled) -> None:
    plan = build_plan(rolled.document)
    assert len(plan) == 33
    assert {step.verb for step in plan.steps} == {"replace"}
    for step in plan.steps:
        assert step.expected_html != step.was_html


def test_no_step_targets_a_heading_chunk(rolled) -> None:
    plan = build_plan(rolled.document)
    assert not [s for s in plan.steps if s.tag in ("h1", "h2", "h3")]
    headings = [b for b in rolled.document.blocks if not b.editable]
    assert len(headings) == 32, "27 note headings, 3 section headings, entity and address"
    assert not [b for b in headings if b.changed], (
        "a heading that differs between skeleton and target would need an edit, and this "
        "design has no step that can make one"
    )


def test_the_instruction_never_asks_for_a_structural_operation(rolled) -> None:
    plan = build_plan(rolled.document)
    uploaded = ChunkMap(rolled.document.html("skeleton"))
    for index, chunk in enumerate(uploaded.chunks):
        object.__setattr__(chunk, "chunk_id", f"chunk-{index}")
    uploaded.by_id = {c.chunk_id: c for c in uploaded.chunks}
    bind_chunk_ids(plan, uploaded)
    for step in plan.steps:
        instruction = step.instruction().lower()
        assert "replace the entire contents" in instruction
        assert "do not add any section" in instruction
        assert "do not change any heading" in instruction
        assert not re.search(r"\b(insert|renumber|create a|append a)\b", instruction)


def test_no_create_verb_anywhere_in_the_build(rolled) -> None:
    """Decision 28: one verb. Checked against our own string literals."""
    banned = ("create_document", "insert_section", "add_section", '"create"', "'create'")
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        joined = "\n".join(literals)
        for word in banned:
            assert word not in joined or "refused" in joined, f"{path.name} mentions {word}"


def test_a_no_op_step_is_refused_because_it_cannot_be_verified(rolled) -> None:
    plan = build_plan(rolled.document)
    plan.steps.append(Step(99, "probe", "p", None, "<p>same</p>", "<p>same</p>"))
    with pytest.raises(PlanRefusedError, match="reads as 'not applied'"):
        assert_plan_is_legal(plan, rolled.document)


def test_a_step_that_targets_a_heading_is_refused(rolled) -> None:
    plan = build_plan(rolled.document)
    plan.steps.append(Step(99, "note-heading", "h3", 4, "<h3>a</h3>", "<h3>b</h3>"))
    with pytest.raises(PlanRefusedError, match="no renumbering step to get wrong"):
        assert_plan_is_legal(plan, rolled.document)


def test_chunk_ids_are_bound_by_content_not_by_position(rolled) -> None:
    plan = build_plan(rolled.document).sample(3)
    uploaded = ChunkMap(rolled.document.html("skeleton"))
    for index, chunk in enumerate(uploaded.chunks):
        object.__setattr__(chunk, "chunk_id", f"chunk-{index}")
    uploaded.by_id = {c.chunk_id: c for c in uploaded.chunks}
    bind_chunk_ids(plan, uploaded)
    assert all(step.chunk_id for step in plan.steps)

    plan.steps[0].was_html = "<p>never uploaded</p>"
    with pytest.raises(PlanRefusedError, match="matches 0 uploaded chunk"):
        bind_chunk_ids(plan, uploaded)


def test_the_expected_post_state_is_the_whole_document(rolled) -> None:
    plan = build_plan(rolled.document).sample(1)
    uploaded = ChunkMap(rolled.document.html("skeleton"))
    for index, chunk in enumerate(uploaded.chunks):
        object.__setattr__(chunk, "chunk_id", f"chunk-{index}")
    uploaded.by_id = {c.chunk_id: c for c in uploaded.chunks}
    bind_chunk_ids(plan, uploaded)
    expected = expected_after(uploaded, plan.steps[0])
    assert len(expected) == len(uploaded)
    changed = [k for k in expected if expected[k] != uploaded.by_id[k].canonical]
    assert changed == [plan.steps[0].chunk_id], "exactly one chunk is expected to move"


def test_sample_mode_takes_a_prefix_and_nothing_else(rolled) -> None:
    plan = build_plan(rolled.document)
    sampled = plan.sample(4)
    assert [s.index for s in sampled.steps] == [1, 2, 3, 4]
    assert plan.sample(None) is plan
