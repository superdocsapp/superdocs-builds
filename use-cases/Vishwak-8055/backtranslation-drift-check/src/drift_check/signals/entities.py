"""Named-entity drift detection.

General open-domain named-entity recognition is out of scope for a
dependency-free deterministic layer (see LIMITATIONS.md #4) — that is
exactly the kind of "semantic interpretation" the AI-assisted layer exists
for. What *is* implemented deterministically, and is the primary defense
here, is exact-match checking of a document's declared ``protected_terms``:
organization names, product names, or other strings the document owner has
said must survive back-translation byte-for-byte. This is high precision by
construction — it can only ever fire on a term the caller explicitly listed.

A secondary, best-effort heuristic also flags capitalized multi-word phrases
(a cheap proper-noun proxy) that appear in the source but not, verbatim, in
the back-translation. It is intentionally lower confidence and severity than
a protected-term miss, precisely because it is a heuristic rather than a
guarantee.
"""

from __future__ import annotations

import re

from drift_check.models import DriftCategory, Severity
from drift_check.signals import Signal

_CAPITALIZED_PHRASE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9&.]*\s?){2,}\b")

# Common sentence-initial capitalization false positives to ignore when
# scanning for proper-noun-like phrases (kept short and easy to extend).
_STOP_STARTS = {"The", "This", "That", "These", "Those", "Any", "All", "It"}


def _excerpt(text: str, start: int, end: int, pad: int = 40) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return f"{prefix}{text[lo:hi].strip()}{suffix}"


def detect_protected_term_drift(
    source_text: str, back_translation_text: str, protected_terms: tuple[str, ...]
) -> list[Signal]:
    signals: list[Signal] = []
    for term in protected_terms:
        if term not in source_text:
            continue  # term isn't referenced in this section
        if term in back_translation_text:
            continue  # survived intact
        signals.append(
            Signal(
                category=DriftCategory.NAMED_ENTITY_CHANGE,
                severity=Severity.HIGH,
                difference=f"Protected term '{term}' present in source but missing verbatim from back-translation",
                evidence_signal=f"protected_term_missing:{term}",
                source_excerpt=_excerpt(source_text, source_text.index(term), source_text.index(term) + len(term)),
                back_translation_excerpt=back_translation_text[:80],
                confidence=0.8,
            )
        )
    return signals


def detect_capitalized_phrase_drift(source_text: str, back_translation_text: str) -> list[Signal]:
    src_phrases = {
        m.group(0).strip()
        for m in _CAPITALIZED_PHRASE.finditer(source_text)
        if m.group(0).split()[0] not in _STOP_STARTS and len(m.group(0).split()) >= 2
    }
    if not src_phrases:
        return []

    signals: list[Signal] = []
    for phrase in sorted(src_phrases):
        if phrase in back_translation_text:
            continue
        idx = source_text.index(phrase)
        signals.append(
            Signal(
                category=DriftCategory.NAMED_ENTITY_CHANGE,
                severity=Severity.MEDIUM,
                difference=f"Capitalized phrase '{phrase}' in source has no verbatim match in back-translation",
                evidence_signal=f"entity_heuristic_missing:{phrase}",
                source_excerpt=_excerpt(source_text, idx, idx + len(phrase)),
                back_translation_excerpt=back_translation_text[:80],
                confidence=0.45,
            )
        )
    return signals
