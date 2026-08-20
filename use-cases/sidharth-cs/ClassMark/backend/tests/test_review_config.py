"""Review-mode/depth configuration tests.

These tests pin the semantic teacher controls to the only raw SuperDocs
parameters the backend is allowed to derive.
"""

import asyncio

import pytest
from pydantic import ValidationError

from app.workflow.review_config import (
    ReviewConfiguration,
    ReviewDepth,
    ReviewMode,
    build_review_instruction,
)
from tests.fakes import FakeSuperDocsClient
from tests.test_orchestrator import _workflow


def test_proofreading_quick_maps_to_core_fast():
    config = ReviewConfiguration(mode="proofreading", depth="quick")
    assert (config.model_tier, config.thinking_depth) == ("core", "fast")


def test_proofreading_standard_maps_to_core_balanced():
    config = ReviewConfiguration(mode="proofreading", depth="standard")
    assert (config.model_tier, config.thinking_depth) == ("core", "balanced")


def test_default_configuration_is_proofreading_standard_core_balanced():
    config = ReviewConfiguration()
    assert config.mode == ReviewMode.PROOFREADING
    assert config.depth == ReviewDepth.STANDARD
    assert (config.model_tier, config.thinking_depth) == ("core", "balanced")


def test_academic_writing_thorough_maps_to_pro_deep():
    config = ReviewConfiguration(mode="academic_writing", depth="thorough")
    assert (config.model_tier, config.thinking_depth) == ("pro", "deep")


def test_every_mode_depth_combination_has_valid_superdocs_configuration():
    for mode in ReviewMode:
        for depth in ReviewDepth:
            additional = "Focus on fragments." if mode == ReviewMode.CUSTOM else ""
            config = ReviewConfiguration(
                mode=mode, depth=depth, additional_instructions=additional
            )
            assert config.model_tier in {"core", "pro"}
            assert config.thinking_depth in {"fast", "balanced", "deep"}
            assert build_review_instruction(config)


def test_invalid_mode_is_rejected():
    with pytest.raises(ValidationError):
        ReviewConfiguration(mode="assignment_alignment")


def test_invalid_depth_is_rejected():
    with pytest.raises(ValidationError):
        ReviewConfiguration(depth="maximum")


def test_raw_superdocs_configuration_is_rejected():
    with pytest.raises(ValidationError):
        ReviewConfiguration(model_tier="max")


def test_custom_requires_teacher_instruction():
    with pytest.raises(ValidationError, match="additional_instructions"):
        ReviewConfiguration(mode="custom", additional_instructions="  ")


def test_custom_with_teacher_instruction_is_accepted_and_safeguarded():
    config = ReviewConfiguration(
        mode="custom",
        depth="standard",
        additional_instructions="Focus especially on sentence fragments.",
    )
    instruction = build_review_instruction(config)
    assert "Focus especially on sentence fragments." in instruction
    assert "replacement text only" in instruction
    assert "student's voice" in instruction
    assert "Do not introduce new claims" in instruction


def test_generated_instructions_retain_integrity_and_voice_safeguards():
    for mode in ReviewMode:
        config = ReviewConfiguration(
            mode=mode,
            additional_instructions="Review sentence fragments." if mode == ReviewMode.CUSTOM else "",
        )
        instruction = build_review_instruction(config)
        for expected in (
            "replacement text only",
            "'Original:' or 'Corrected:'",
            "'Changes made:' or 'List of changes:'",
            "Any explanation must stay separate",
            "student's voice",
            "intended meaning",
            "factual content",
            "Do not introduce new claims",
            "teacher approval",
        ):
            assert expected in instruction
        assert "showing the original text and the corrected text" not in instruction


def test_workflow_persists_semantic_choice_and_sends_derived_values():
    fake = FakeSuperDocsClient(approve_succeeds=True)
    workflow = _workflow(fake_superdocs=fake)
    asyncio.run(workflow.retrieve_submission())
    asyncio.run(workflow.upload_to_superdocs())

    config = ReviewConfiguration(mode="academic_writing", depth="thorough")
    data = asyncio.run(workflow.start_review(config))

    assert data.review_mode == "academic_writing"
    assert data.review_depth == "thorough"
    assert fake.chat_calls[0]["approval_mode"] == "ask_every_time"
    assert fake.chat_calls[0]["model_tier"] == "pro"
    assert fake.chat_calls[0]["thinking_depth"] == "deep"


def test_default_workflow_configuration_sends_core_balanced_with_native_hitl():
    fake = FakeSuperDocsClient(approve_succeeds=True)
    workflow = _workflow(fake_superdocs=fake)
    asyncio.run(workflow.retrieve_submission())
    asyncio.run(workflow.upload_to_superdocs())

    asyncio.run(workflow.start_review(ReviewConfiguration()))

    assert fake.chat_calls[0]["approval_mode"] == "ask_every_time"
    assert fake.chat_calls[0]["model_tier"] == "core"
    assert fake.chat_calls[0]["thinking_depth"] == "balanced"
