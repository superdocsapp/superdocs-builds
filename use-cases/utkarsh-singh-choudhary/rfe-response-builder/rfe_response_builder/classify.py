"""
RFE-type classification.

Every RFE notice this package has handled so far gets the exact same
generic instruction shape regardless of what kind of petition it's
responding to. That leaves real signal on the table: an H-1B specialty
occupation RFE, a marriage-based (I-130) bona fides RFE, and an EB-1A
extraordinary ability RFE each have well-established regulatory anchors
an attorney would want surfaced up front, and the officer's specific
concerns tend to cluster around different things for each.

This module classifies a notice into one of a small set of known
categories and returns a `CategoryProfile` with a short, conservative
legal-framework note for that category, to append to the drafting
instruction and surface in the UI.

Deliberately a deterministic, keyword-scored classifier -- NOT a trained
ML model. Consistent with the rest of this package's philosophy
(`rfe.py`'s matching is exact/stemmed keyword overlap, not a black box):
every classification decision here is traceable to which signal phrases
actually appeared in the notice text, which `classify()` returns
alongside the category so a reviewer can see exactly why a category was
picked instead of trusting an opaque score. `UNKNOWN` is returned,
honestly, whenever no category clears a minimum confidence bar --
this must never guess a specific petition type it has no real signal
for, since a wrong category confidently asserted (e.g. citing H-1B
regulations in a marriage-based case) is worse than surfacing nothing.

The legal-framework notes name well-established, long-stable regulatory
sections (8 CFR provisions that have anchored these petition types for
years) -- these are the kind of citations any immigration text or CFR
lookup will confirm, not case-specific legal research. Even so, every
note is written to be explicitly a "starting point to verify" pointer,
not a legal conclusion, and gets appended to instructions with that
framing intact -- this tool still does not practice law.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class RFECategory(str, Enum):
    H1B_SPECIALTY_OCCUPATION = "h1b_specialty_occupation"
    MARRIAGE_BONA_FIDES = "marriage_bona_fides"
    EB1A_EXTRAORDINARY_ABILITY = "eb1a_extraordinary_ability"
    UNKNOWN = "unknown"


@dataclass
class CategoryProfile:
    category: RFECategory
    display_name: str
    legal_framework_note: str  # appended to drafting instructions, and shown in the UI
    checklist_label: str  # short label shown next to the coverage checklist


_PROFILES: dict[RFECategory, CategoryProfile] = {
    RFECategory.H1B_SPECIALTY_OCCUPATION: CategoryProfile(
        category=RFECategory.H1B_SPECIALTY_OCCUPATION,
        display_name="H-1B Specialty Occupation",
        legal_framework_note=(
            "This appears to be an H-1B specialty occupation RFE. The regulatory framework "
            "an attorney would typically start from is 8 CFR 214.2(h)(4)(iii)(A), which sets "
            "out the specialty-occupation criteria (degree requirement is common to the "
            "industry, the employer normally requires a degree for the position, the duties "
            "are so specialized/complex that a degree is required, or a bachelor's degree "
            "is normally the minimum for entry). Verify which specific criterion the officer's "
            "concern maps to before drafting -- do not assume all four apply."
        ),
        checklist_label="H-1B specialty occupation",
    ),
    RFECategory.MARRIAGE_BONA_FIDES: CategoryProfile(
        category=RFECategory.MARRIAGE_BONA_FIDES,
        display_name="Marriage-Based Petition (Bona Fides)",
        legal_framework_note=(
            "This appears to be a marriage-based petition RFE concerning bona fides. The "
            "regulatory anchor an attorney would typically start from is 8 CFR "
            "204.2(a)(1)(iii), covering the types of evidence used to establish a bona fide "
            "marital relationship (joint ownership of property, joint tenancy, commingled "
            "finances, children born of the relationship, affidavits from third parties with "
            "personal knowledge, or other evidence of an ongoing relationship). Verify which "
            "specific evidentiary gap the officer identified before drafting."
        ),
        checklist_label="Marriage-based (bona fides)",
    ),
    RFECategory.EB1A_EXTRAORDINARY_ABILITY: CategoryProfile(
        category=RFECategory.EB1A_EXTRAORDINARY_ABILITY,
        display_name="EB-1A Extraordinary Ability",
        legal_framework_note=(
            "This appears to be an EB-1A extraordinary ability RFE. The regulatory anchor an "
            "attorney would typically start from is 8 CFR 204.5(h)(3), listing the ten "
            "evidentiary criteria (at least three of which must generally be met absent a "
            "one-time achievement), commonly analyzed under the two-step Kazarian framework "
            "(evidentiary criteria met, then final merits determination). Verify which "
            "specific criterion or step the officer's concern targets before drafting."
        ),
        checklist_label="EB-1A extraordinary ability",
    ),
    RFECategory.UNKNOWN: CategoryProfile(
        category=RFECategory.UNKNOWN,
        display_name="Unclassified",
        legal_framework_note="",
        checklist_label="Unclassified filing type",
    ),
}

# Signal phrases per category, each a (phrase, weight) pair. Weights are
# deliberately small integers, not tuned probabilities -- this stays a
# transparent point-scoring system, not a model whose weights need
# explaining. Multi-word phrases score higher than single generic words
# since they're much less likely to appear by coincidence in an
# unrelated notice.
_SIGNALS: dict[RFECategory, list[tuple[str, int]]] = {
    RFECategory.H1B_SPECIALTY_OCCUPATION: [
        ("specialty occupation", 3),
        ("h-1b", 3),
        ("h1b", 3),
        ("bachelor's degree", 1),
        ("degree requirement", 2),
        ("labor condition application", 2),
        ("lca", 1),
        ("theoretical and practical application", 2),
        ("body of highly specialized knowledge", 2),
    ],
    RFECategory.MARRIAGE_BONA_FIDES: [
        ("bona fide marriage", 3),
        ("bona fide marital relationship", 3),
        ("marriage certificate", 2),
        ("joint bank statements", 2),
        ("joint lease", 1),
        ("i-130", 2),
        ("spousal relationship", 2),
        ("commingle finances", 2),
        ("commingling of finances", 2),
        ("affidavits from third parties", 1),
    ],
    RFECategory.EB1A_EXTRAORDINARY_ABILITY: [
        ("extraordinary ability", 3),
        ("eb-1", 2),
        ("eb1a", 3),
        ("sustained national or international acclaim", 3),
        ("kazarian", 3),
        ("final merits determination", 2),
        ("original contributions of major significance", 2),
        ("critical or essential capacity", 1),
        ("judging the work of others", 1),
        ("awards for excellence", 1),
    ],
}

# A category must clear this many total points before it's returned
# instead of UNKNOWN -- calibrated so a single incidental single-word
# match (e.g. a stray "degree") can't misclassify a notice; it takes
# either one strong multi-word phrase or several weaker signals.
_MIN_CONFIDENCE_THRESHOLD = 3


@dataclass
class ClassificationResult:
    category: RFECategory
    score: int
    matched_signals: list[str] = field(default_factory=list)
    all_scores: dict[str, int] = field(default_factory=dict)  # category value -> score, for transparency

    @property
    def profile(self) -> CategoryProfile:
        return _PROFILES[self.category]


def classify(notice_text: str) -> ClassificationResult:
    """Scores the full notice text against each category's signal
    phrases and returns the highest-scoring category, or UNKNOWN if
    nothing clears `_MIN_CONFIDENCE_THRESHOLD`. Case-insensitive
    substring matching -- deliberately simple and auditable rather than
    tokenized/stemmed, since these are mostly fixed legal phrases where
    exact wording matters (e.g. "bona fide marriage" as a phrase carries
    real signal that its individual stemmed words don't)."""
    lowered = " ".join(notice_text.lower().split())
    scores: dict[RFECategory, int] = {}
    matches_by_category: dict[RFECategory, list[str]] = {}

    for category, signals in _SIGNALS.items():
        total = 0
        matched = []
        for phrase, weight in signals:
            if phrase in lowered:
                total += weight
                matched.append(phrase)
        scores[category] = total
        matches_by_category[category] = matched

    best_category = max(scores, key=lambda c: scores[c]) if scores else RFECategory.UNKNOWN
    best_score = scores.get(best_category, 0)

    all_scores = {c.value: s for c, s in scores.items()}

    if best_score < _MIN_CONFIDENCE_THRESHOLD:
        return ClassificationResult(category=RFECategory.UNKNOWN, score=best_score,
                                     matched_signals=[], all_scores=all_scores)

    return ClassificationResult(
        category=best_category, score=best_score,
        matched_signals=matches_by_category[best_category], all_scores=all_scores,
    )


def get_profile(category: RFECategory) -> CategoryProfile:
    return _PROFILES[category]


# --- Response deadline extraction --------------------------------------------
#
# Missing an RFE deadline is one of the worst failure modes in this domain
# (an unanswered RFE typically results in denial). This is a best-effort
# extractor over common phrasings USCIS notices use -- it surfaces what it
# finds with the exact matched sentence for verification, and returns None
# rather than guessing when nothing matches. This is NOT a substitute for
# reading the actual notice date/deadline off the physical document -- it's
# a "did you catch this" surface, always paired with the raw matched text
# so a human can immediately verify it against the source.

_DEADLINE_PATTERNS = [
    re.compile(r"(?:within|no later than)\s+(\d{1,3})\s+calendar\s+days", re.IGNORECASE),
    re.compile(r"(?:within|no later than)\s+(\d{1,3})\s+days", re.IGNORECASE),
    re.compile(r"respond(?:ed)?\s+(?:to this (?:notice|request)\s+)?within\s+(\d{1,3})\s+days", re.IGNORECASE),
]

_DEADLINE_SENTENCE_RE = re.compile(r"[^.]*\b(?:within|no later than)\b[^.]*\d{1,3}\s*(?:calendar\s+)?days[^.]*\.",
                                    re.IGNORECASE)


@dataclass
class DeadlineInfo:
    days: int | None
    matched_sentence: str | None

    @property
    def found(self) -> bool:
        return self.days is not None


def extract_response_deadline(notice_text: str) -> DeadlineInfo:
    """Best-effort extraction of the stated response window (e.g. "you
    must respond within 87 days"). Returns `DeadlineInfo(days=None,
    matched_sentence=None)` -- not an exception, not a guess -- if no
    recognizable phrasing is found; the caller/UI is responsible for
    telling the human to check the notice by hand in that case, exactly
    as they'd have had to before this function existed."""
    for pattern in _DEADLINE_PATTERNS:
        m = pattern.search(notice_text)
        if m:
            days = int(m.group(1))
            sentence_match = _DEADLINE_SENTENCE_RE.search(notice_text)
            matched_sentence = sentence_match.group(0).strip() if sentence_match else m.group(0).strip()
            return DeadlineInfo(days=days, matched_sentence=matched_sentence)
    return DeadlineInfo(days=None, matched_sentence=None)
