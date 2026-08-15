"""
The claim-element taxonomy this assembler tracks against, and the
keyword-based tagger that decides which source paragraphs bear on which
element.

Implementation note (same honest disclosure as Task 1's enrich.py): this is
a deterministic, rule-based keyword/phrase tagger, not a live LLM call --
this cloud build environment cannot reach api.superdocs.app or a general
LLM API directly (see PROGRESS.md). A production version would swap
`tag_paragraph()` for a real extraction call (through SuperDocs' own
document AI, which is exactly what this build is meant to sit in front of);
the rest of the pipeline -- ingest -> tag -> assemble -> detect
contradictions -> track dependencies -- does not change shape when that
swap happens.

The five elements below are standard asylum/withholding claim elements
(particular social group, persecution, nexus, state protection,
internal relocation) -- textbook doctrine, not anything proprietary to a
real case.
"""
import re

ELEMENTS = [
    {
        "id": "particular_social_group",
        "label": "Particular social group / protected-ground membership",
        "keywords": [
            r"union organizer", r"organizing committee", r"labor movement",
            r"publicly identified", r"distinct(?:ly)? (?:and )?recognizable group",
            r"union membership", r"identified (?:as|themselves) as",
        ],
    },
    {
        "id": "persecution_or_harm",
        "label": "Past persecution or well-founded fear of future harm",
        "keywords": [
            r"attack(?:ed|s)?", r"assaulted", r"injured", r"threat(?:s|ened)?",
            r"intimidation", r"violence",
        ],
    },
    {
        "id": "nexus",
        "label": "Nexus — harm on account of the protected ground",
        "keywords": [
            r"on account of", r"on that basis", r"targeted", r"union hall",
            r"union('s)? (?:local )?office", r"because (?:of|they)",
        ],
    },
    {
        "id": "state_protection",
        "label": "State action, or state unable/unwilling to protect",
        "keywords": [
            r"police", r"investigat\w*", r"labor rights protection unit",
            r"ministry", r"prosecut\w*", r"arrest\w*", r"suspect",
            r"municipal", r"state\b",
        ],
    },
    {
        "id": "internal_relocation",
        "label": "No reasonable internal relocation alternative",
        "keywords": [
            r"relocat\w*", r"another region", r"safe elsewhere", r"move to",
            r"internal flight",
        ],
    },
]

_ELEMENT_PATTERNS = {
    el["id"]: re.compile("|".join(el["keywords"]), re.IGNORECASE)
    for el in ELEMENTS
}

# Polarity lexicon used only for the state_protection element, to detect
# when two sources disagree about whether protection is actually available.
# This is deliberately narrow and disclosed as a heuristic, not a general
# sentiment model.
PROTECTION_AVAILABLE_TERMS = [
    r"formation of a labor rights protection unit",
    r"tasked specifically with",
    r"response requirement",
    r"committed to protecting",
]
PROTECTION_UNAVAILABLE_TERMS = [
    r"no (?:suspect|arrest)", r"not (?:been )?(?:meaningfully )?(?:investigat\w*|pursued)",
    r"declin(?:ed|ing) to open", r"not aware of any dedicated",
    r"no case in our .* caseload", r"no documented follow-up",
    r"no operational capacity",
]
_AVAIL_RE = re.compile("|".join(PROTECTION_AVAILABLE_TERMS), re.IGNORECASE)
_UNAVAIL_RE = re.compile("|".join(PROTECTION_UNAVAILABLE_TERMS), re.IGNORECASE)


def tag_paragraph(paragraph_text):
    """Return the list of element ids whose keyword pattern matches this
    paragraph's text."""
    return [eid for eid, pat in _ELEMENT_PATTERNS.items() if pat.search(paragraph_text)]


def relevance_score(paragraph_text, element_id):
    """Count of DISTINCT keyword patterns (not raw occurrences) that hit
    this paragraph for the given element -- used to rank which paragraph is
    the strongest match when a source has more than one paragraph tagged
    for the same element."""
    el = next(e for e in ELEMENTS if e["id"] == element_id)
    return sum(1 for kw in el["keywords"] if re.search(kw, paragraph_text, re.IGNORECASE))


def protection_polarity(paragraph_text):
    """+1 if the paragraph reads as asserting protection is available,
    -1 if it reads as asserting protection is unavailable/unproven,
    0 if neither pattern matches (no polarity signal)."""
    avail = bool(_AVAIL_RE.search(paragraph_text))
    unavail = bool(_UNAVAIL_RE.search(paragraph_text))
    if avail and not unavail:
        return 1
    if unavail and not avail:
        return -1
    return 0


if __name__ == "__main__":
    for el in ELEMENTS:
        print(f"{el['id']}: {el['label']}")
