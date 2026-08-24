"""Deterministic drift signals.

Every detector in this package takes ``(source_text, back_translation_text)``
— both already in the source language, since back-translation's whole point
is to make that comparison possible — and returns zero or more ``Signal``
objects. A ``Signal`` is a candidate finding: it always carries a severity
and confidence, but ``drift_engine`` decides how it becomes (or doesn't
become) a ``DriftFinding``.

These detectors are regex/rule based on purpose. They currently cover
English source text only (see LIMITATIONS.md #2); the ``language`` argument
is threaded through so additional languages can be added as new marker
tables without touching the orchestration logic below.
"""

from __future__ import annotations

from dataclasses import dataclass

from drift_check.models import DriftCategory, Severity

SUPPORTED_LEXICAL_LANGUAGES = frozenset({"en"})


@dataclass(frozen=True, slots=True)
class Signal:
    category: DriftCategory
    severity: Severity
    difference: str
    evidence_signal: str
    source_excerpt: str
    back_translation_excerpt: str
    confidence: float
    literal_replacement: tuple[str, str] | None = None  # (find, replace) in the *target* text


def run_all_detectors(
    source_text: str,
    back_translation_text: str,
    *,
    language: str = "en",
    protected_terms: tuple[str, ...] = (),
) -> list[Signal]:
    from drift_check.signals import entities, lexical, numeric

    if language not in SUPPORTED_LEXICAL_LANGUAGES:
        return []

    signals: list[Signal] = []
    signals.extend(lexical.detect_modal_drift(source_text, back_translation_text))
    signals.extend(lexical.detect_negation_drift(source_text, back_translation_text))
    signals.extend(lexical.detect_qualifier_drift(source_text, back_translation_text))
    signals.extend(numeric.detect_numeric_drift(source_text, back_translation_text))
    signals.extend(entities.detect_protected_term_drift(source_text, back_translation_text, protected_terms))
    signals.extend(entities.detect_capitalized_phrase_drift(source_text, back_translation_text))
    return signals
