"""Backend-owned review configuration for the teacher-facing workflow.

The browser supplies only the teacher's semantic choice (mode, depth, and
optional additional instructions). This module is the sole authority that
turns those choices into a SuperDocs instruction and model configuration.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewMode(StrEnum):
    PROOFREADING = "proofreading"
    WRITING_QUALITY = "writing_quality"
    ACADEMIC_WRITING = "academic_writing"
    CUSTOM = "custom"


class ReviewDepth(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    THOROUGH = "thorough"


_DEPTH_TO_SUPERDOCS = {
    ReviewDepth.QUICK: ("core", "fast"),
    ReviewDepth.STANDARD: ("core", "balanced"),
    ReviewDepth.THOROUGH: ("pro", "deep"),
}

_MODE_INSTRUCTIONS = {
    ReviewMode.PROOFREADING: (
        "Edit this document to fix grammar, spelling, punctuation, usage, and "
        "other obvious mechanical errors. Correct misspelled words, subject-verb "
        "agreement errors, comma splices, and repetition. Do not rewrite correct "
        "sentences merely because an alternative sounds better."
    ),
    ReviewMode.WRITING_QUALITY: (
        "Edit this document to improve clarity, sentence structure, awkward "
        "phrasing, unnecessary repetition, transitions, and flow. Preserve the "
        "student's voice and intended meaning."
    ),
    ReviewMode.ACADEMIC_WRITING: (
        "Edit this document to improve academic clarity, paragraph coherence, "
        "organization, transitions, formal academic style, and sentence quality "
        "appropriate to the student's existing level. Do not artificially make "
        "the writing sound like graduate-level or professional writing."
    ),
}

_NON_NEGOTIABLE_SAFEGUARDS = (
    "For every proposed document edit, propose the corrected replacement "
    "text only — the replacement must be just the corrected or revised "
    "sentence or phrase, without labels such as 'Original:' or 'Corrected:', "
    "without phrases such as 'Changes made:' or 'List of changes:', and "
    "without commentary or explanation. Any explanation must stay separate "
    "from the replacement content. Preserve the student's voice, intended "
    "meaning, factual content, and original argument. Do not introduce new "
    "claims. Do not rewrite correct text merely for stylistic preference. "
    "Every proposed document change remains subject to teacher approval."
)


class ReviewConfiguration(BaseModel):
    """Validated semantic configuration received from the teacher UI."""

    model_config = ConfigDict(extra="forbid")

    mode: ReviewMode = ReviewMode.PROOFREADING
    depth: ReviewDepth = ReviewDepth.STANDARD
    additional_instructions: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def custom_requires_instruction(self) -> "ReviewConfiguration":
        if self.mode == ReviewMode.CUSTOM and not self.additional_instructions.strip():
            raise ValueError("additional_instructions is required for Custom review")
        return self

    @property
    def model_tier(self) -> str:
        return _DEPTH_TO_SUPERDOCS[self.depth][0]

    @property
    def thinking_depth(self) -> str:
        return _DEPTH_TO_SUPERDOCS[self.depth][1]


DEFAULT_REVIEW_CONFIGURATION = ReviewConfiguration()


def build_review_instruction(config: ReviewConfiguration) -> str:
    """Build the exact review instruction sent to SuperDocs.

    Safety and data-integrity requirements are deliberately appended after
    teacher-provided text, so Custom mode cannot override them.
    """
    if config.mode == ReviewMode.CUSTOM:
        focus = (
            "Follow this teacher-defined review focus, while obeying all of the "
            "safety and approval requirements below:\n"
            f"{config.additional_instructions.strip()}"
        )
        additional = ""
    else:
        focus = _MODE_INSTRUCTIONS[config.mode]
        additional = config.additional_instructions.strip()

    parts = [focus]
    if additional:
        parts.append(f"Additional teacher instructions: {additional}")
    parts.append(_NON_NEGOTIABLE_SAFEGUARDS)
    return " ".join(parts)


# Kept as the backwards-compatible backend default endpoint value. It is
# derived from the builder rather than maintained as a competing constant.
DEFAULT_REVIEW_INSTRUCTION = build_review_instruction(DEFAULT_REVIEW_CONFIGURATION)
