"""Modal obligation, negation, and qualifier detectors (English).

Modal strength scale
---------------------
Every modal/obligation phrase maps to an integer on a single axis, so a
"change in obligation" reduces to "did the number change, and by how much":

    -2  PROHIBITED    must not, shall not, may not, cannot, is prohibited from
    -1  DISCOURAGED   should not, ought not to
     0  PERMITTED     may, can, is permitted to, is allowed to
    +1  RECOMMENDED   should, is recommended to, ought to
    +2  OBLIGATORY    must, shall, is required to, has to

A drift is reported only when the *aligned* occurrence (matched by order of
appearance within the section) changes strength. Synonyms within the same
tier ("must" vs "is required to") therefore never fire — this is what makes
section 7's PASS examples pass. The severity of a reported drift is derived
from the size of the jump: |Δ| ≥ 2 crosses a whole obligation/prohibition
boundary (CRITICAL); |Δ| == 1 softens or hardens by one tier (HIGH).
"""

from __future__ import annotations

import re
from collections import Counter

from drift_check.models import DriftCategory, Severity
from drift_check.signals import Signal

# Ordered longest-phrase-first so multi-word phrases are matched before any
# single-word phrase that is a substring of them (see module docstring in
# signals/__init__.py — this file builds the master alternation from this
# list, sorted by descending word count, so "may not" outranks "may").
_MODAL_PHRASES: list[tuple[str, int]] = [
    ("must not", -2),
    ("must never", -2),
    ("shall not", -2),
    ("may not", -2),
    ("cannot", -2),
    ("can not", -2),
    ("is not permitted to", -2),
    ("are not permitted to", -2),
    ("is not allowed to", -2),
    ("are not allowed to", -2),
    ("is prohibited from", -2),
    ("are prohibited from", -2),
    ("is strictly prohibited from", -2),
    ("should not", -1),
    ("ought not to", -1),
    ("is discouraged from", -1),
    ("is required to", 2),
    ("are required to", 2),
    ("is obligated to", 2),
    ("are obligated to", 2),
    ("has to", 2),
    ("have to", 2),
    ("must", 2),
    ("shall", 2),
    ("is recommended to", 1),
    ("are recommended to", 1),
    ("is advised to", 1),
    ("are advised to", 1),
    ("ought to", 1),
    ("should", 1),
    ("is permitted to", 0),
    ("are permitted to", 0),
    ("is allowed to", 0),
    ("are allowed to", 0),
    ("is entitled to", 0),
    ("are entitled to", 0),
    ("may", 0),
    ("can", 0),
]

_STRENGTH_LABEL = {
    -2: "PROHIBITED",
    -1: "DISCOURAGED",
    0: "PERMITTED",
    1: "RECOMMENDED",
    2: "OBLIGATORY",
}


def _build_modal_pattern() -> re.Pattern[str]:
    ordered = sorted(_MODAL_PHRASES, key=lambda p: -len(p[0]))
    alternation = "|".join(re.escape(phrase) for phrase, _ in ordered)
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


_MODAL_PATTERN = _build_modal_pattern()
_PHRASE_TO_STRENGTH = {phrase.lower(): strength for phrase, strength in _MODAL_PHRASES}


def _find_modals(text: str) -> list[tuple[re.Match[str], int]]:
    out = []
    for m in _MODAL_PATTERN.finditer(text):
        strength = _PHRASE_TO_STRENGTH[m.group(0).lower()]
        out.append((m, strength))
    return out


def _excerpt(text: str, start: int, end: int, pad: int = 40) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return f"{prefix}{text[lo:hi].strip()}{suffix}"


def detect_modal_drift(source_text: str, back_translation_text: str) -> list[Signal]:
    src_modals = _find_modals(source_text)
    bt_modals = _find_modals(back_translation_text)

    signals: list[Signal] = []
    paired = min(len(src_modals), len(bt_modals))
    for i in range(paired):
        src_match, src_strength = src_modals[i]
        bt_match, bt_strength = bt_modals[i]
        delta = bt_strength - src_strength
        if delta == 0:
            continue
        severity = Severity.CRITICAL if abs(delta) >= 2 else Severity.HIGH
        src_word = src_match.group(0)
        bt_word = bt_match.group(0)
        signals.append(
            Signal(
                category=DriftCategory.MODAL_OBLIGATION_CHANGE,
                severity=severity,
                difference=(
                    f"Obligation strength changed: '{src_word}' "
                    f"({_STRENGTH_LABEL[src_strength]}) → '{bt_word}' "
                    f"({_STRENGTH_LABEL[bt_strength]})"
                ),
                evidence_signal=f"modal:{src_word.upper()}->{bt_word.upper()}",
                source_excerpt=_excerpt(source_text, src_match.start(), src_match.end()),
                back_translation_excerpt=_excerpt(back_translation_text, bt_match.start(), bt_match.end()),
                confidence=0.95,
            )
        )

    if len(src_modals) != len(bt_modals) and paired == 0:
        # No aligned pair to compare (e.g. one side has zero modal phrases) —
        # still worth a low-confidence flag rather than silence.
        if src_modals or bt_modals:
            signals.append(
                Signal(
                    category=DriftCategory.MODAL_OBLIGATION_CHANGE,
                    severity=Severity.MEDIUM,
                    difference="Number of modal/obligation phrases differs between source and back-translation",
                    evidence_signal=f"modal_count:{len(src_modals)}->{len(bt_modals)}",
                    source_excerpt=_excerpt(source_text, 0, min(60, len(source_text))),
                    back_translation_excerpt=_excerpt(back_translation_text, 0, min(60, len(back_translation_text))),
                    confidence=0.4,
                )
            )
    return signals


# --- Negation (outside of modal phrases already handled above) ------------

_NEGATION_WORDS = [
    "without",
    "never",
    "none",
    "neither",
    "nor",
    "not",
    "cannot",
    "can't",
    "won't",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "doesn't",
    "don't",
    "didn't",
    "prohibited",
]
_NEGATION_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in sorted(_NEGATION_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _non_modal_negation_spans(text: str) -> list[re.Match[str]]:
    modal_spans = [(m.start(), m.end()) for m, _ in _find_modals(text)]

    def inside_modal(m: re.Match[str]) -> bool:
        return any(lo <= m.start() < hi for lo, hi in modal_spans)

    return [m for m in _NEGATION_PATTERN.finditer(text) if not inside_modal(m)]


def detect_negation_drift(source_text: str, back_translation_text: str) -> list[Signal]:
    src_hits = _non_modal_negation_spans(source_text)
    bt_hits = _non_modal_negation_spans(back_translation_text)

    src_counts = Counter(m.group(0).lower() for m in src_hits)
    bt_counts = Counter(m.group(0).lower() for m in bt_hits)

    if src_counts == bt_counts:
        return []

    vanished = src_counts - bt_counts
    added = bt_counts - src_counts
    if not vanished and not added:
        return []

    # A marker present in source and completely absent in the back
    # translation (or vice-versa) is a stronger signal than a partial count
    # shift (e.g. "not" appearing twice vs once in a longer section).
    clean_reversal = bool(vanished) != bool(added)
    severity = Severity.CRITICAL if clean_reversal else Severity.HIGH

    parts = []
    if vanished:
        parts.append("removed: " + ", ".join(f"'{w}'×{c}" for w, c in vanished.items()))
    if added:
        parts.append("added: " + ", ".join(f"'{w}'×{c}" for w, c in added.items()))
    difference = "Negation marker(s) changed — " + "; ".join(parts)

    src_excerpt = _excerpt(source_text, src_hits[0].start(), src_hits[0].end()) if src_hits else source_text[:60]
    bt_excerpt = (
        _excerpt(back_translation_text, bt_hits[0].start(), bt_hits[0].end()) if bt_hits else back_translation_text[:60]
    )

    return [
        Signal(
            category=DriftCategory.NEGATION_REVERSAL,
            severity=severity,
            difference=difference,
            evidence_signal=f"negation:{dict(vanished)}->{dict(added)}",
            source_excerpt=src_excerpt,
            back_translation_excerpt=bt_excerpt,
            confidence=0.85 if clean_reversal else 0.6,
        )
    ]


# --- Qualifiers -------------------------------------------------------------

# "High-weight" qualifiers bound scope, minimums/maximums, or exclusivity —
# removing or adding one changes what a clause actually requires, not just
# its tone. "Lower-weight" qualifiers are softer hedges. See DECISIONS.md #5.
_HIGH_WEIGHT_QUALIFIERS = {
    "at least",
    "at most",
    "only",
    "exclusively",
    "no later than",
    "no more than",
    "unless",
    "except",
    "solely",
}
_LOW_WEIGHT_QUALIFIERS = {
    "approximately",
    "generally",
    "primarily",
    "potentially",
    "roughly",
    "up to",
    "typically",
    "usually",
}
_ALL_QUALIFIERS = _HIGH_WEIGHT_QUALIFIERS | _LOW_WEIGHT_QUALIFIERS
_QUALIFIER_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(q) for q in sorted(_ALL_QUALIFIERS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def detect_qualifier_drift(source_text: str, back_translation_text: str) -> list[Signal]:
    src_counts = Counter(m.group(0).lower() for m in _QUALIFIER_PATTERN.finditer(source_text))
    bt_counts = Counter(m.group(0).lower() for m in _QUALIFIER_PATTERN.finditer(back_translation_text))

    if src_counts == bt_counts:
        return []

    vanished = src_counts - bt_counts
    added = bt_counts - src_counts
    changed_terms = set(vanished) | set(added)
    if not changed_terms:
        return []

    is_high_weight = bool(changed_terms & _HIGH_WEIGHT_QUALIFIERS)
    severity = Severity.HIGH if is_high_weight else Severity.MEDIUM

    parts = []
    if vanished:
        parts.append("removed: " + ", ".join(f"'{w}'" for w in vanished))
    if added:
        parts.append("added: " + ", ".join(f"'{w}'" for w in added))
    difference = "Qualifier(s) changed — " + "; ".join(parts)

    src_match = _QUALIFIER_PATTERN.search(source_text)
    bt_match = _QUALIFIER_PATTERN.search(back_translation_text)
    src_excerpt = _excerpt(source_text, src_match.start(), src_match.end()) if src_match else source_text[:60]
    bt_excerpt = (
        _excerpt(back_translation_text, bt_match.start(), bt_match.end()) if bt_match else back_translation_text[:60]
    )

    return [
        Signal(
            category=DriftCategory.QUALIFIER_CHANGE,
            severity=severity,
            difference=difference,
            evidence_signal=f"qualifier:{dict(vanished)}->{dict(added)}",
            source_excerpt=src_excerpt,
            back_translation_excerpt=bt_excerpt,
            confidence=0.75,
        )
    ]
