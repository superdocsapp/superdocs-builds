"""Proposed-correction generation.

Every ``ProposedCorrection`` has ``correction_target="translation"`` — this
is a ``Literal`` type, not a convention, so nothing in this codebase can
construct a correction that targets the source (mypy rejects any other
value at the call site).

Two ways a correction gets its text:

- **Deterministic literal replacement**: only for categories where the
  drifted token is language-invariant — digits, currency figures, percentage
  figures — and only when that exact literal string is found in the target
  text to replace. This is a mechanical find/replace, safe to propose
  automatically because it never involves generating new target-language
  prose.
- **Instruction only**: for every other category (modal, negation,
  qualifier, entity, semantic-only), the correction is a precise
  natural-language instruction for the human reviewer rather than
  auto-generated foreign-language text this system cannot independently
  verify. See LIMITATIONS.md #6 for why this boundary is deliberate.
"""

from __future__ import annotations

from drift_check.models import DriftCategory, ProposedCorrection, SemanticAssessment
from drift_check.signals import Signal

_CATEGORY_INSTRUCTIONS: dict[DriftCategory, str] = {
    DriftCategory.MODAL_OBLIGATION_CHANGE: (
        "Restore the obligation/permission level in the translation to match the source's modal strength."
    ),
    DriftCategory.NEGATION_REVERSAL: "Restore the negation in the translation to match the source.",
    DriftCategory.NUMERIC_CHANGE: "Restore the numeric value in the translation to match the source.",
    DriftCategory.DATE_CHANGE: "Restore the date in the translation to match the source.",
    DriftCategory.PERCENTAGE_CHANGE: "Restore the percentage in the translation to match the source.",
    DriftCategory.UNIT_CHANGE: (
        "Restore the unit in the translation to match the source, converting the value if the "
        "translation is meant to keep a different unit system."
    ),
    DriftCategory.QUALIFIER_CHANGE: "Restore the qualifier/scope wording in the translation to match the source.",
    DriftCategory.NAMED_ENTITY_CHANGE: "Restore the exact named entity in the translation to match the source.",
    DriftCategory.SCOPE_CHANGE: "Restore the original scope of the clause in the translation.",
    DriftCategory.TERMINOLOGY_CHANGE: "Restore the source terminology in the translation.",
    DriftCategory.CONDITION_CHANGE: "Restore the original condition in the translation.",
    DriftCategory.SEMANTIC_DRIFT_OTHER: "Review this section against the source and correct the meaning drift.",
}


def build_correction_for_signal(signal: Signal, target_text: str) -> ProposedCorrection:
    suggested_text = None
    if signal.literal_replacement:
        find, replace = signal.literal_replacement
        if find and find in target_text:
            suggested_text = target_text.replace(find, replace)

    base_instruction = _CATEGORY_INSTRUCTIONS.get(
        signal.category, "Review this section against the source and correct the meaning drift."
    )
    instruction = f"{base_instruction} Detected change: {signal.difference}"

    return ProposedCorrection(
        correction_target="translation",
        suggested_text=suggested_text,
        instruction=instruction,
        auto_generated_by="deterministic",
    )


def build_correction_for_signal_group(signals: list[Signal], target_text: str) -> ProposedCorrection:
    """Consolidated correction for two or more corroborating signals of the same category.

    Applies every signal's literal replacement to a single working copy of
    the target text, in order. If any signal in the group lacks a literal
    replacement (or its expected substring can't be found — e.g. a prior
    replacement already touched that span), the whole group falls back to an
    instruction covering every detected change rather than proposing a
    partially-edited text a reviewer might mistake for complete.
    """
    if len(signals) == 1:
        return build_correction_for_signal(signals[0], target_text)

    working_text = target_text
    fully_literal = True
    for signal in signals:
        if signal.literal_replacement and signal.literal_replacement[0] in working_text:
            find, replace = signal.literal_replacement
            working_text = working_text.replace(find, replace)
        else:
            fully_literal = False

    suggested_text = working_text if fully_literal and working_text != target_text else None

    seen_instructions: dict[str, None] = {}
    for signal in signals:
        base = _CATEGORY_INSTRUCTIONS.get(
            signal.category, "Review this section against the source and correct the meaning drift."
        )
        seen_instructions[base] = None
    combined_instruction = " ".join(seen_instructions)
    detail = " | ".join(s.difference for s in signals)

    return ProposedCorrection(
        correction_target="translation",
        suggested_text=suggested_text,
        instruction=f"{combined_instruction} Detected changes ({len(signals)} corroborating signals): {detail}",
        auto_generated_by="deterministic",
    )


def build_correction_for_semantic(assessment: SemanticAssessment) -> ProposedCorrection:
    category = assessment.category or DriftCategory.SEMANTIC_DRIFT_OTHER
    base_instruction = _CATEGORY_INSTRUCTIONS.get(category, _CATEGORY_INSTRUCTIONS[DriftCategory.SEMANTIC_DRIFT_OTHER])
    instruction = (
        f"{base_instruction} No deterministic rule corroborates this finding — it rests on the AI "
        f"semantic read alone, so review the source and translation directly before editing. "
        f"Assessment: {assessment.rationale}"
    )
    return ProposedCorrection(
        correction_target="translation",
        suggested_text=None,
        instruction=instruction,
        auto_generated_by="ai_assisted",
    )
