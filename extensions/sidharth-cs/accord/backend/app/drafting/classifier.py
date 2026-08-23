"""The correction-vs-addition classifier (design doc §14) — the same
two-independent-signals discipline Task 1 used for injection detection, and
the same zero-model-call philosophy Task 1 used for sanctions matching:
free, instant, fully explainable, deterministic.

Important design property, stated in the plan verbatim: classification only
influences how an instruction is *framed* before being sent to SuperDocs. It
never determines whether transcript content is preserved — an
incorrectly-classified utterance still gets forwarded, just framed as the
wrong instruction template. Reduced editing precision is acceptable;
information loss is not.

`build_structured_instruction` extends the framing layer: it splits the
batch into sentences, routes each to the template section its keywords
match (heuristic, never AI), and attaches structural-preservation
constraints. The downstream LLM still does the actual edit, but the space it
can edit in is deliberately constrained — the Phase A benchmarks showed that
an unconstrained "integrate this anywhere" instruction produces misplaced
facts, mutated headings, and verbatim transcript leakage.
"""

from __future__ import annotations

import html as html_module
import logging
import re
from dataclasses import dataclass, field

ADDITION = "addition"
CORRECTION = "correction"

# Signal A: a correction-cue phrase. One signal alone false-positives too
# easily ("no" as filler; "actually" as a verbal tic) — this is deliberately
# never used on its own, only combined with Signal B below.
_CORRECTION_CUES = (
    "no,",
    "actually,",
    # "Actually the budget is $55,000" — the same repair without the comma
    # Whisper often omits. Requiring the comma meant the most natural
    # phrasing of a correction was read as a brand-new fact.
    "actually ",
    "i meant",
    "scratch that",
    "change ",
    # How people actually flag a repair out loud. "correction" and "sorry"
    # were both missing, so "Sorry, correction — the total budget is
    # $55,000, not $45,000" scored zero cues and classified as an ADDITION:
    # the document kept the old figure and gained nothing.
    "correction",
    "sorry,",
    "my mistake",
    # The contrastive form, which states both values at once. Without this
    # the "not X" half was invisible and only the new figure registered.
    " not $",
    ", not ",
    # "should be" is deliberately NOT a cue: "the website should be
    # delivered by October 30th" / "should include X" is obligation/future
    # language, not a repair (benchmark run 2 misclassified a timeline
    # batch as CORRECTION when the draft contained the word "should").
)

# Signal B candidates: numbers/money/percentages, and capitalized
# proper-noun-shaped words. Deliberately simple regexes, not NLP — the goal
# is "does this utterance reference something already in the draft," not
# perfect entity extraction.
_VALUE_PATTERN = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
_PROPER_NOUN_PATTERN = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")


# The batcher's "flush immediately" trigger, deliberately NARROWER than the
# classification cues above. A flush from Batcher.add() runs inline on the
# transcript consumer, so the consumer stops pulling events for as long as
# the batch takes to draft — 30-60s of SuperDocs round trips — and the panel
# shows nothing arriving, then the whole backlog at once. Widening the
# classification cues ("correction", "sorry,", "actually ", ", not ") to
# catch more spoken repairs therefore also made that stall fire far more
# often. Classification keeps the wide set; only the flush trigger stays
# narrow, so recognising a repair never costs a live transcript stall.
_FLUSH_CUES = (
    "no,",
    "actually,",
    "i meant",
    "scratch that",
)


def has_flush_cue(text: str) -> bool:
    """Should the batcher close the buffer right now? See _FLUSH_CUES."""
    lowered = (text or "").lower()
    return any(cue in lowered for cue in _FLUSH_CUES)


# Punctuation-tolerant cue detection. The substring list below cannot see the
# forms real speech actually produces: Whisper transcribed a live repair as
# "Our total budget is $45,000. Actually." / "no make it $55,000." — a PERIOD
# after "actually", and no comma after "no". Every cue in _CORRECTION_CUES
# missed both halves, so the repair classified as an ADDITION and the document
# gained a second budget line instead of replacing the first.
_CUE_RE = re.compile(
    # "actually" as a word, whatever punctuation follows it
    r"\bactually\b"
    # a segment that OPENS with a bare "no" — "no make it $55,000". Anchored so
    # it never fires on "does not include" or a mid-sentence "no".
    r"|(?:^|[.!?]\s*)no\b"
    r"|\bscratch that\b|\bi meant\b|\bmy mistake\b"
    r"|\bcorrection\b|\bsorry\b",
    re.IGNORECASE,
)


def has_correction_cue(text: str) -> bool:
    """Signal A alone — also used by the Batcher as the "flush immediately"
    trigger. Fine for that: over-triggering there just means an earlier,
    smaller call, not a wrong classification (full two-signal classify()
    below is what actually decides ADDITION vs CORRECTION)."""
    lowered = (text or "").lower()
    return bool(_CUE_RE.search(lowered)) or any(
        cue in lowered for cue in _CORRECTION_CUES
    )


def _candidate_values(text: str) -> list[str]:
    return _VALUE_PATTERN.findall(text) + _PROPER_NOUN_PATTERN.findall(text)


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "")


def _has_value_overlap(text: str, current_draft_html: str) -> bool:
    draft_text = _strip_html(current_draft_html).lower()
    if not draft_text.strip():
        return False  # nothing to overlap with yet — e.g. the very first utterance
    return any(candidate.lower() in draft_text for candidate in _candidate_values(text))


# Values of a KIND that a correction replaces in place. A repair states the
# NEW value ("make it $55,000"); the OLD one is what sits in the draft. So
# the plain overlap test — does a value in this sentence already appear in
# the document — is exactly backwards for the most natural phrasing of a
# correction, and only fired when the speaker happened to restate the old
# value too ("September 20th, not September 15th").
# Split immediately BEFORE a correction cue, keeping the cue with the
# clause it introduces.
def _merge_cue_only(sentences: list[str]) -> list[str]:
    """A sentence that is nothing but a cue marks the sentence AFTER it.

    Whisper punctuates a spoken repair as two sentences — "Correction."
    then "November 15th." — and splitting on that boundary sent the cue to
    the correction operation (carrying no value at all) and the actual new
    value to a separate addition. Two SuperDocs calls, and the repair had
    nothing to repair with. Attach the marker to what it introduces."""
    out: list[str] = []
    carry = ""
    for sentence in sentences:
        if _CUE_ONLY_RE.match(sentence.strip()):
            carry = f"{carry} {sentence}".strip()
            continue
        out.append(f"{carry} {sentence}".strip() if carry else sentence)
        carry = ""
    if carry:
        out.append(carry)
    return out


# A part left holding nothing but a correction cue after the repair it
# introduced has been consumed — "Actually,", "no,", "sorry -".
_CUE_ONLY_RE = re.compile(
    r"^\W*(?:actually|scratch that|i meant|no|sorry|correction|my mistake)\W*$",
    re.IGNORECASE,
)

_CUE_SPLIT = re.compile(
    r"(?=\b(?:actually|scratch that|i meant)\b|\bno,)", re.IGNORECASE
)

# Must END on a digit. "[\d,]*" is greedy and swallows a comma that merely
# follows the figure, so "the budget is $55,000, not $45,000" yielded the
# value "$55,000," — which then matched nothing in the draft, so the
# correction could not find what it was replacing. The identical fix was
# already made to validator._MONEY_RE; this copy never got it.
_MONEY_VALUE_RE = re.compile(r"\$\s?\d[\d,]*\d(?:\.\d+)?|\$\s?\d(?:\.\d+)?")
# Months spelled out here rather than reusing _MONTHS, which is defined
# further down the module.
_DATE_VALUE_RE = re.compile(
    r"(?:january|february|march|april|may|june|july|august|september|october"
    r"|november|december)\s+\d{1,2}(?:st|nd|rd|th)?"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b",
    re.IGNORECASE,
)


def _replaces_a_value_of_the_same_kind(text: str, draft_text: str) -> bool:
    """True when the sentence states a money/date value and the document
    already carries a DIFFERENT value of that same kind — the shape of a
    replacement, which is what "actually, make it $55,000" is."""
    for pattern in (_MONEY_VALUE_RE, _DATE_VALUE_RE):
        said = {m.group(0).strip().lower() for m in pattern.finditer(text)}
        have = {m.group(0).strip().lower() for m in pattern.finditer(draft_text)}
        if said and have and (said - have):
            return True
    return False


def resolve_intra_batch_correction(text: str) -> str:
    """Drop a value the speaker corrects within the SAME batch.

    A repair usually follows its mistake immediately — "Our total budget is
    $45,000. Actually, no, make it $55,000." — so both land in one batch.
    Classification then sees a draft that does not yet hold $45,000, reads
    the repair as new information, and hands SuperDocs two competing
    figures; the live run left Budget empty rather than choose. Here the
    superseded sentence is removed before any of that, so the batch carries
    only the value that survived.
    """
    parts = _SENTENCE_SPLIT.split(text or "")
    # A repair does not wait for a full stop. Whisper transcribed the live
    # audio as "Our total budget is $45,000, Actually, no, make it $55,000."
    # — one sentence by punctuation, two by meaning. Splitting only on .!?
    # bailed out here and let both figures through, and the document ended
    # up narrating the change instead of making it.
    parts = [p for chunk in parts for p in _CUE_SPLIT.split(chunk) if p.strip()]
    if len(parts) < 2:
        return text
    for pattern in (_MONEY_VALUE_RE, _DATE_VALUE_RE):
        # The last cue-bearing sentence that states a value of this kind.
        winner = next(
            (
                i for i in range(len(parts) - 1, -1, -1)
                if has_correction_cue(parts[i]) and pattern.search(parts[i])
            ),
            None,
        )
        if winner is None:
            continue
        kept = {m.group(0).strip().lower() for m in pattern.finditer(parts[winner])}
        superseded = []
        for i, sentence in enumerate(parts):
            if i >= winner:
                continue
            said = {m.group(0).strip().lower() for m in pattern.finditer(sentence)}
            # Only drop a sentence whose values are ALL superseded — a
            # sentence carrying other facts as well must survive intact.
            if said and not (said & kept):
                superseded.append(i)
        if superseded:
            # Rewrite the FIRST superseded sentence with the surviving value
            # and drop the repair, rather than the other way round. Dropping
            # the sentence and keeping the repair leaves a bare fragment —
            # "Actually, no, make it $55,000." — which carries the value but
            # not what the value IS. Sent to SuperDocs as content, it reads
            # as an instruction with no referent: the live gate log shows it
            # answering with heading markup and no $55,000 anywhere, so the
            # figure never reached Budget and the section stayed empty.
            # Carrying the value back into its own sentence yields "Our total
            # budget for this is $55,000." — a statement that says what it
            # means, and whose anchor is the value itself.
            new_value = pattern.search(parts[winner])
            host = superseded[0]
            rewritten = pattern.sub(new_value.group(0), parts[host], count=1)
            parts[host] = rewritten
            drop = set(superseded[1:]) | {winner}
            parts = [p for i, p in enumerate(parts) if i not in drop]
    # _CUE_SPLIT breaks "Actually, no, make it $55,000." at both cues, so the
    # leading "Actually," survives as its own part once the repair itself is
    # consumed. It carries no fact and is not filler by the general test
    # (it is a real word), but shipping it to SuperDocs as content invites
    # exactly the confusion this function exists to prevent.
    parts = [p for p in parts if not _CUE_ONLY_RE.match(p.strip())]
    out = re.sub(r"\s{2,}", " ", " ".join(p.strip() for p in parts if p.strip())).strip()
    # Rewriting "starts September 15th, no, make it September 20th." leaves the
    # comma that introduced the repair dangling at the end. Close the sentence
    # instead of shipping the artifact.
    return re.sub(r"[,;]\s*$", ".", out)


def classify(text: str, current_draft_html: str) -> str:
    """Both signals required for CORRECTION; otherwise ADDITION. See the
    module docstring — this asymmetry is deliberate, not an oversight.

    Negation/exclusion statements are never corrections: "The project does
    not include X" is a NEW fact (routes to Out of Scope), not a repair of
    an existing value — even when a word overlaps the draft ("project")."""
    if _is_negation_sentence(text):
        return ADDITION
    if not has_correction_cue(text):
        return ADDITION
    if _has_value_overlap(text, current_draft_html):
        return CORRECTION
    # Signal B, replacement form: the cue plus a new value of a kind the
    # document already holds. Still two independent signals — a cue alone
    # never reclassifies, and a value alone never does either.
    if _replaces_a_value_of_the_same_kind(text, _strip_html(current_draft_html)):
        return CORRECTION
    return ADDITION


def build_instruction(classification: str, text: str) -> str:
    """The SuperDocs chat `message`.  A strong source-grounding preamble
    prevents the LLM from inventing facts not present in the transcript."""

    # Source-grounding preamble — every instruction starts with this.
    # The LLM must treat the document as a form to fill from evidence,
    # not a canvas for creative writing.
    _GROUNDING = (
        "SOURCE-GROUNDING RULE: Only add or change facts explicitly stated "
        "in the instruction below. Never invent project names, client names, "
        "dates, budgets, timelines, deliverables, technologies, business "
        "objectives, participants, assumptions, or any other factual content "
        "not present in the transcript. If a section of the document has no "
        "supporting evidence, leave it unchanged. Do not add example values, "
        "placeholder text, or suggested content. An incomplete but truthful "
        "document is correct; a polished fabricated document is a defect.\n\n"
    )

    if classification == CORRECTION:
        return _GROUNDING + (
            f'Correction from the conversation: "{text}". This replaces an existing '
            "value or statement — locate the specific value being corrected and update "
            "it in place. Do not duplicate the old value. Do not touch unrelated sections."
        )
    return _GROUNDING + (
        f'New information from the conversation: "{text}". Integrate this into the '
        "appropriate section of the document, preserving everything already present. "
        "Do not touch unrelated sections."
    )


# ---------------------------------------------------------------------------
# Structured instruction layer (Phase A fix)
# ---------------------------------------------------------------------------
#
# Every rule is (primary_patterns, context_patterns, heading_substrings).
# A sentence routes to a section only when at least one PRIMARY pattern
# matches. Context patterns reinforce but never route alone — a sentence
# matching only context patterns goes to unmatched (the LLM decides, the
# gate validates). This prevents single-word hijacking ("kickoff" →
# Timeline, "pricing" → Budget, "milestone" → Timeline in the 70s
# benchmark).
#
# Primary = high-precision (date anchors, dollar amounts, proper nouns).
# Context  = high-recall but ambiguous (kickoff, milestone, pricing).

_MONTHS = r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
_ORDINALS = r"\b\d{1,2}(?:st|nd|rd|th)\b"

_DATE_PRIMARY = [
    rf"{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?",
    rf"{_MONTHS}",
    _ORDINALS,
    r"\b(?:starts? on|begins? on|delivered by|completed by|deadline)\b",
]
_DATE_CONTEXT = [
    r"\b(?:starts?|begins?|kickoff|finalize|timeline|milestone|schedule|delivery|launch)\b",
]

_NUMBER_WORDS = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
    r"fifty|sixty|seventy|eighty|ninety)"
)
_BUDGET_PRIMARY = [
    r"\$\s?\d[\d,]*",
    r"\b\d{2,}\s*(?:thousand|hundred|million|billion)\b",
    # spoken amounts: "forty-five thousand", "forty five thousand", "eighteen hundred"
    rf"\b{_NUMBER_WORDS}(?:[-\s]{_NUMBER_WORDS})?\s*(?:thousand|hundred|million|billion)\b",
]
_BUDGET_CONTEXT = [
    r"\b(?:dollars?|budget|cost|fee|pricing|investment|payment|paid|total|dollar)\b",
]

_SCOPE_PRIMARY: list[str] = []  # scope has no standalone anchors — always context-guided
_SCOPE_CONTEXT = [
    r"\b(?:modern responsive|responsive website|browse products|add items to (?:the|a) cart|checkout|e-commerce|website where customers)\b",
    # Scope named directly rather than described — "the scope covers data
    # ingestion, transformation, and the dashboard".
    r"\b(?:the\s+)?scope\s+(?:covers|includes|is|consists of)\b",
    r"\bwork\s+(?:covers|includes)\b",
]

_DELIVERABLE_PRIMARY = [
    r"\bdeliverables?\s+(?:should\s+)?(?:include|cover|comprise|contain|consist of|encompass)\b",
]
_DELIVERABLE_CONTEXT = [
    r"\b(?:deliverables?|payment integration|analytics|responsive design)\b",
]

_OUT_OF_SCOPE_PRIMARY = [
    # Full negation phrases — strong signal
    r"(?:is|are)\s+not\s+(?:part\s+of|included\s+in|within)\s+(?:the\s+)?(?:scope|project)",
    r"does\s+not\s+include",
    r"\b(?:doesn['’]?t|don['’]?t)\s+include\b",
    r"\b(?:excluded?|exclusions?|outside|beyond)\s+(?:the\s+)?scope\b",
    r"\bnot\s+(?:covered|in\s+scope)\b",
    # Fragment-tolerant forms (70s benchmark: "Not include ongoing...")
    r"^\s*not\s+include\s",
    r"^\s*not\s+part\s+of\s+(?:the\s+)?(?:scope|project)",
    r"\b(?:isn['']?t|aren['']?t)\s+(?:part\s+of|included\sin|within)\s+(?:the\s+)?scope",
    r"\bexcluded?\s+from\b",
    r"\boutside\s+(?:the\s+)?scope\b",
]
_OUT_OF_SCOPE_CONTEXT: list[str] = []

_ASSUMPTIONS_PRIMARY = [
    r"\b(?:client|we['’]?ll|we will)\s+(?:will\s+)?(?:provide|supply|furnish|give|send|share)\b",
    # passive: "pricing will be supplied by the client" / "provided by the client"
    r"\b(?:will\s+be\s+)?(?:supplied|provided|furnished|given|sent|shared)\s+by\s+(?:the\s+)?(?:client|customer)\b",
    # Governance: reporting cadence and milestone sign-off are mutual
    # expectations, so they belong with the other responsibilities. Without
    # a rule these matched nothing and fell through to "most appropriate
    # section", where the same sentence landed in Assumptions on one run and
    # under the Project Details table on the next.
    r"\b(?:weekly|daily|monthly|regular)\s+(?:progress\s+)?(?:updates?|reports?|check-?ins?|meetings?)\b",
    r"\b(?:progress|status)\s+(?:updates?|reports?)\b",
    r"\breview\s+(?:each|every|the)\s+milestones?\b",
    # "We assume the identity provider will remain Okta." had no rule and
    # fell through to the fallback in the Requirements List transcript.
    r"\bwe\s+assume\b",
    r"\bassuming\s+(?:that\s+)?\w",
    r"\b(?:the\s+)?assumption\s+is\b",
]
_ASSUMPTIONS_CONTEXT = [
    r"\b(?:access to|existing|branding assets|product images|descriptions?|pricing data|domain)\b",
]

_NEXT_STEPS_PRIMARY = [
    # "kick-off" is how it is actually said and transcribed; the bare
    # "kickoff" spelling matched neither the hyphen nor the two-word form, and
    # "finalize requirements" missed the article people invariably use. Both
    # near-misses left the sentence unrouted, so it fell through to the
    # model's own choice of section — live, "We want to have a kick-off
    # meeting next week to finalize the requirements" landed under Timeline &
    # Milestones, which "next week" makes an entirely reasonable guess.
    r"\b(?:next steps?|kick[\s-]?off|after approval|"
    r"finalize\s+(?:the\s+)?requirements|begin development|move forward)\b",
    # Assigned action items — "Sarah will send the deck by Friday", "I'll
    # follow up". Minutes carry these constantly and nothing else claimed
    # them, so they fell through to whatever section the model preferred.
    r"\b[A-Z][a-z]+\s+will\s+(?:send|share|circulate|prepare|draft|follow up|"
    r"review|confirm|schedule|set up|own|take)\b",
    r"\b(?:i|we|you|they)(?:'ll| will)\s+(?:send|share|circulate|prepare|draft|"
    r"follow up|confirm|schedule|set up)\b",
    r"\baction\s+items?\b",
]
_NEXT_STEPS_CONTEXT: list[str] = []

_PROJECT_PRIMARY: list[str] = []  # project identification has no standalone anchors
_PROJECT_CONTEXT = [
    r"\b(?:company|business|e-commerce|client|firm|organization)\b",
]

# ---------------------------------------------------------------------------
# Non-SOW template rules.
#
# _SECTION_RULES is one shared, priority-ordered list, but a rule can only
# fire when the ACTIVE draft actually contains a matching heading — an
# unmatched heading falls straight through to the next rule. So rules whose
# headings exist only in Meeting Minutes / Advice Note / Requirements cannot
# change Statement of Work routing. The two that DO touch SOW (Objectives,
# and the Matter/Details widening) are deliberately high-precision and sit
# below the existing scope/deliverable rules.
#
# Everything unmatched still reaches the document via the "most appropriate
# section" fallback; these rules exist to make placement deterministic
# rather than a per-run coin flip.
# ---------------------------------------------------------------------------

# --- Meeting Minutes -------------------------------------------------------
_DECISIONS_PRIMARY = [
    r"\bwe(?:'ve| have)?\s+(?:decided|agreed|concluded|settled on)\b",
    r"\b(?:the\s+)?decision\s+(?:is|was|has been)\b",
    r"\b(?:we|it)\s+(?:was\s+)?agreed\s+(?:that|to|on)\b",
    r"\bconsensus\s+(?:is|was)\b",
    r"\bwe\s+discussed\b",
]
_DECISIONS_CONTEXT: list[str] = []

_ATTENDEES_PRIMARY = [
    r"\b(?:joining\s+us|in\s+attendance|attendees?\s+(?:are|is|include))\b",
    r"\b(?:present|here)\s+today\b",
    r"\bon\s+the\s+call\s+(?:today\s+)?(?:we\s+have|are|is)\b",
]
_ATTENDEES_CONTEXT: list[str] = []

_AGENDA_PRIMARY = [
    r"\b(?:the\s+)?agenda\s+(?:is|for|today|includes)\b",
    r"(?i)\b(?:today\s+)?we(?:'ll| will)\s+(?:cover|go through|run through|walk through)\b",
    r"\b(?:first|second|third|next)\s+(?:item|topic)\b",
]
_AGENDA_CONTEXT: list[str] = []

# "The next meeting is scheduled for September 2nd" was landing in Timeline
# via the date rules, or nowhere. Checked before them for Minutes.
_NEXT_MEETING_PRIMARY = [
    r"\b(?:the\s+)?next\s+(?:meeting|session|call|sync)\b",
    r"\bwe(?:'ll| will)\s+(?:meet|reconvene)\s+again\b",
    r"\breconvene\b",
]
_NEXT_MEETING_CONTEXT: list[str] = []

# --- Advice Note -----------------------------------------------------------
_RECOMMENDATION_PRIMARY = [
    r"\bwe\s+recommend\b",
    r"\b(?:our|the)\s+recommendations?\s+(?:is|are|would be)\b",
    r"\bwe(?:'d| would)\s+recommend\b",
]
_RECOMMENDATION_CONTEXT: list[str] = []

_RISK_PRIMARY = [
    r"\b(?:the\s+)?risks?\s+(?:is|are|here|includes?)\b",
    r"\b(?:a\s+)?(?:key\s+)?(?:concern|consideration|exposure|liability)\b",
    r"\bcareful\s+(?:of|about)\b",
    r"\bcould\s+expose\b",
]
_RISK_CONTEXT: list[str] = []

_ADVICE_PRIMARY = [
    r"\b(?:our|my)\s+advice\s+(?:is|would be)\b",
    r"\bwe\s+advise\b",
    r"\byou\s+should\s+(?:not\s+)?(?:proceed|consider|ensure|avoid|seek)\b",
    r"\bwe\s+suggest\b",
]
_ADVICE_CONTEXT: list[str] = []

_QUESTIONS_PRIMARY = [
    r"\b(?:the\s+)?questions?\s+(?:is|are|raised|being asked)\b",
    r"\b(?:they|you|the client)\s+(?:want|wants)\s+to\s+know\b",
    r"\b(?:asking|asked)\s+whether\b",
    r"\bquer(?:y|ies)\b",
]
_QUESTIONS_CONTEXT: list[str] = []

_BACKGROUND_PRIMARY = [
    r"\b(?:by\s+way\s+of\s+)?background\b",
    r"\b(?:the\s+)?(?:situation|context)\s+(?:is|was)\b",
    r"\bhistorically\b",
    r"\bwhat\s+happened\s+(?:is|was)\b",
]
_BACKGROUND_CONTEXT: list[str] = []

# --- Requirements List -----------------------------------------------------
# Non-functional checked BEFORE functional: "the system must handle 10,000
# users" matches both shapes, and the performance reading is the right one.
_NONFUNCTIONAL_PRIMARY = [
    r"\b(?:performance|uptime|availability|latency|throughput|scalab\w*)\b",
    r"\bmust\s+(?:handle|support|scale)\b",
    r"\b(?:response\s+time|load\s+time|concurrent\s+users?)\b",
    r"\b(?:secure|security|encryption|compliance|accessib\w*)\b",
]
_NONFUNCTIONAL_CONTEXT: list[str] = []

_FUNCTIONAL_PRIMARY = [
    r"\b(?:the\s+)?(?:system|user|users|application|app)\s+(?:must|should|shall|can|will)\b",
    r"\bable\s+to\b",
    r"\b(?:feature|functionality)\s+(?:for|to|that)\b",
]
_FUNCTIONAL_CONTEXT: list[str] = []

_CONSTRAINTS_PRIMARY = [
    r"\b(?:the\s+)?constraints?\s+(?:is|are|include)\b",
    r"\b(?:limited|restricted)\s+to\b",
    r"\bmust\s+(?:use|run on|integrate with)\b",
    r"\b(?:cannot|can't)\s+exceed\b",
]
_CONSTRAINTS_CONTEXT: list[str] = []

# --- Proposal --------------------------------------------------------------
# Proposal routed 3 of its 10 sections before these existed: Client Needs and
# Proposed Solution had no rules at all, and "the timeline is eight weeks
# from kickoff" carries no month or ordinal so the date rule never fired.
# Everything fell to the "most appropriate section" fallback — the same
# configuration a live run proved scatters facts into the wrong sections.
_CLIENT_NEEDS_PRIMARY = [
    r"\byour (?:main )?(?:need|needs|problem|challenge|pain)\b",
    r"\b(?:you|they)\s+(?:need|needs|want|wants|require|requires)\b",
    r"\bfrom what you(?:'ve| have)?\s+(?:described|told us|said)\b",
    r"\bcurrently\s+(?:takes|spend|spends|struggle|struggles)\b",
]
_CLIENT_NEEDS_CONTEXT: list[str] = []

_PROPOSED_SOLUTION_PRIMARY = [
    r"\b(?:our|the)\s+proposed\s+solution\b",
    r"\bwe\s+(?:propose|recommend building|would build)\b",
    r"\bthe\s+solution\s+(?:is|would be)\b",
]
_PROPOSED_SOLUTION_CONTEXT: list[str] = []

# Durations, not calendar dates — "eight weeks from kickoff", "a 12 week
# engagement". The date rules only recognise months and ordinals.
_DURATION_PRIMARY = [
    rf"\b(?:{_NUMBER_WORDS}|\d{{1,3}})[\s-]*(?:day|days|week|weeks|month|months|sprint|sprints)\b",
    r"\b(?:the\s+)?timeline\s+is\b",
    r"\bfrom\s+kick-?off\b",
]
_DURATION_CONTEXT: list[str] = []

_WHY_US_PRIMARY = [
    r"\bwe(?:'ve| have)\s+(?:built|delivered|done|worked on)\b",
    r"\bour\s+(?:team|experience|track record|expertise)\b",
    r"\bwe\s+specialize\b",
    r"\bwe(?:'ve| have)\s+been\s+(?:doing|building)\b",
]
_WHY_US_CONTEXT: list[str] = []

# --- Objectives (Statement of Work + Proposal) ------------------------------
# High precision on purpose: this is the one addition that can fire inside a
# SOW, and it sits below the scope/deliverable rules so concrete scope
# language keeps winning.
_OBJECTIVES_PRIMARY = [
    r"\b(?:the\s+)?(?:goal|objective|aim)\s+(?:is|are|of this)\b",
    r"\bwe\s+(?:want|need|hope)\s+to\s+(?:achieve|increase|reduce|improve|grow)\b",
    r"\bsuccess\s+(?:looks like|means|is measured)\b",
]
_OBJECTIVES_CONTEXT: list[str] = []

# (primary_patterns, context_patterns, heading_substrings) — priority order
# top to bottom. PRIMARY match required to route; context reinforces.
_SECTION_RULES: list[tuple[list[str], list[str], list[str]]] = [
    (_OUT_OF_SCOPE_PRIMARY, _OUT_OF_SCOPE_CONTEXT, ["out of scope", "exclusion", "not included"]),
    (_BUDGET_PRIMARY, _BUDGET_CONTEXT, ["budget", "commercial", "investment", "fee", "cost", "pricing", "terms"]),
    (_NEXT_MEETING_PRIMARY, _NEXT_MEETING_CONTEXT, ["next meeting"]),
    (_DATE_PRIMARY, _DATE_CONTEXT, ["timeline", "milestone", "schedule", "start date", "duration", "delivery"]),
    # Durations after calendar dates: a batch naming both a month and a
    # length should still be read as a date.
    (_CLIENT_NEEDS_PRIMARY, _CLIENT_NEEDS_CONTEXT, ["client needs", "problem"]),
    (_PROPOSED_SOLUTION_PRIMARY, _PROPOSED_SOLUTION_CONTEXT, ["proposed solution", "approach"]),
    (_DURATION_PRIMARY, _DURATION_CONTEXT, ["timeline", "schedule", "duration"]),
    # Template-specific rules. None of these headings exist in a Statement of
    # Work, so they cannot alter SOW routing; they sit high because their
    # phrasing is explicit ("we decided", "we recommend") and should win over
    # the generic scope/project rules in the templates that do have them.
    (_DECISIONS_PRIMARY, _DECISIONS_CONTEXT, ["discussion", "decision"]),
    (_ATTENDEES_PRIMARY, _ATTENDEES_CONTEXT, ["attendee", "participant", "present"]),
    (_AGENDA_PRIMARY, _AGENDA_CONTEXT, ["agenda"]),
    (_RECOMMENDATION_PRIMARY, _RECOMMENDATION_CONTEXT, ["recommendation"]),
    (_RISK_PRIMARY, _RISK_CONTEXT, ["risk", "consideration"]),
    (_ADVICE_PRIMARY, _ADVICE_CONTEXT, ["advice"]),
    (_QUESTIONS_PRIMARY, _QUESTIONS_CONTEXT, ["question"]),
    (_BACKGROUND_PRIMARY, _BACKGROUND_CONTEXT, ["background"]),
    (_NONFUNCTIONAL_PRIMARY, _NONFUNCTIONAL_CONTEXT, ["non-functional", "nonfunctional"]),
    (_FUNCTIONAL_PRIMARY, _FUNCTIONAL_CONTEXT, ["functional requirement"]),
    (_CONSTRAINTS_PRIMARY, _CONSTRAINTS_CONTEXT, ["constraint"]),
    (_WHY_US_PRIMARY, _WHY_US_CONTEXT, ["why us", "about us", "our team"]),
    (_SCOPE_PRIMARY, _SCOPE_CONTEXT, ["scope of work"]),
    (_DELIVERABLE_PRIMARY, _DELIVERABLE_CONTEXT, ["deliverable", "solution"]),
    # Below scope/deliverable: concrete scope language must keep winning over
    # a goal statement that happens to mention the same thing.
    (_OBJECTIVES_PRIMARY, _OBJECTIVES_CONTEXT, ["objective", "goal"]),
    (_ASSUMPTIONS_PRIMARY, _ASSUMPTIONS_CONTEXT, ["assumption", "dependency", "client", "responsibilit"]),
    (_NEXT_STEPS_PRIMARY, _NEXT_STEPS_CONTEXT, ["next step", "action item", "next meeting", "approval"]),
    # "matter" widens this to the Advice Note's "Matter Details" table, the
    # direct analogue of Project Details.
    (_PROJECT_PRIMARY, _PROJECT_CONTEXT, ["project", "client", "matter"]),
]

_HEADING_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)

logger = logging.getLogger("classifier")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Conversational openers stripped from the start of a fact (never from the
# middle — a fact's body is preserved as spoken, just cleaned at the edges).
# `(?:\s+|$)` — an opener at the very end of a sentence ("Hi.") still
# strips; the old `\s+`-only requirement left a lone "Hi." intact, which
# became a meaningless required content anchor and made the gate reject
# valid proposals that correctly omitted the filler.
_FILLER_OPENERS = re.compile(
    r"^(?:hi[,.]?|hello[,.]?|hey[,.]?|okay[,.]?|ok[,.]?|yeah[,.]?|yep[,.]?|"
    r"yes[,.]?|no[,.]?|right[,.]?|thanks[,.]?|thank you[,.]?|um[,.]?|uh[,.]?|"
    r"so[,.]?|and[,.]?|or[,.]?|but[,.]?|i['’]d like to|we need (?:to )?|"
    r"i think|basically[,.]?)"
    r"(?:\s+|$)",
    re.IGNORECASE,
)

# A fact that reduces to nothing but standalone conversational filler after
# opener-stripping — produces zero content anchors and must never be sent
# to SuperDocs as a "fact".
_FILLER_ONLY = re.compile(
    r"^(?:hi|hello|hey|okay|ok|yeah|yep|yes|no|right|thanks|thank you|um|uh|so|and)"
    r"[.!?,;:]*$",
    re.IGNORECASE,
)


# Conservative ASR-boundary recovery: when transcript chunks join without
# punctuation ("after launch We want to have a kickoff"), a lowercase word
# followed by a common SENTENCE-STARTER word is a probable missing boundary.
# The starter whitelist keeps proper-noun pairs ("Northstar Goods") and
# title-case nouns ("Acme Corp") from being misread as new sentences, and
# avoids splitting legitimate continuations ("15th and the final website").
_SENTENCE_STARTERS = (
    r"We|I|The|Our|This|It|They|He|She|You|There|That|When|What|How|"
    r"Here|Now|Therefore|However|After|Before|During|Once|Next|Finally|"
    r"Additionally|Meanwhile|Consequently|Moreover|Furthermore|Since|While"
)
_POST_ASR_BOUNDARY = re.compile(
    rf"(?<=[a-z])\.?\s+(?=(?:{_SENTENCE_STARTERS})\s+[a-zA-Z])"
)


def _recover_sentence_boundaries(text: str) -> list[str]:
    r"""Post-split ASR boundary recovery. After .?! splitting, each piece
    is scanned for lowercase→starter-word transitions — a probable
    unpunctuated sentence boundary.
    "after launch We want to have" → split.
    "for Northstar Goods a" → NOT split (proper noun, not a starter).
    "The client is Acme Corp and" → NOT split (proper noun, no starter).
    "15th and the final website" → NOT split ("and" not a starter)."""
    sentences = _SENTENCE_SPLIT.split(text)
    result: list[str] = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        subs = _POST_ASR_BOUNDARY.split(s)
        for sub in subs:
            sub = sub.strip()
            if sub:
                result.append(sub)
    return result


# Whisper's own hallucinations. Fed near-silent audio it does not return
# empty text — it emits sign-off phrases learned from the video captions it
# was trained on. Confirmed from a live meeting: a silent stretch became
# "we'll see you next time", which then merged into a real sentence and
# reached the exported document as "We expect weekly progress updates and
# we'll see you next time." These are never meeting content.
_ASR_HALLUCINATION_RE = re.compile(
    r"\b(?:"
    r"we'?ll see you (?:next time|again)|see you next time|"
    r"thanks? (?:for|so much for) watching|thank you for watching|"
    r"don'?t forget to subscribe|please subscribe|like and subscribe|"
    r"subtitles? by|transcription by|amara\.org|"
    r"\[music\]|\[applause\]|\[silence\]|\[blank_audio\]"
    r")\b",
    re.IGNORECASE,
)


def strip_asr_hallucinations(text: str) -> str:
    """Remove ASR sign-off artifacts from a transcript line, leaving the
    real speech around them intact."""
    cleaned = _ASR_HALLUCINATION_RE.sub(" ", text or "")
    # Tidy what the removal leaves behind: "updates and we'll see you next
    # time." becomes "updates and ." before this runs. Conjunction first,
    # then the orphaned space, or the space is reinstated by the removal.
    cleaned = re.sub(r"\s*\b(?:and|but|or)\b\s*(?=[,.;!?]|$)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(?=[,.;!?])", "", cleaned)
    cleaned = re.sub(r"([,.;!?])\s*\1+", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    # Nothing but leftover punctuation means the line was pure artifact.
    return "" if not re.search(r"[a-zA-Z0-9]", cleaned) else cleaned


def is_filler_only(text: str) -> bool:
    """True when a fact is nothing but conversational filler after opener
    stripping — it carries no content a document could or should contain."""
    stripped = (text or "").strip()
    if stripped and not strip_asr_hallucinations(stripped):
        return True  # the line was nothing but an ASR artifact
    return bool(_FILLER_ONLY.match(stripped))


# A fact is "meaningful" when it contains a recoverable atomic fact:
# a date, a money amount, a proper-noun entity, or enough content words to
# be a real statement. Grammatically incomplete fragments ("Our total",
# "After launch.") carry no recoverable fact and must not become document
# content. Short-but-real facts ("$45,000", "September 15th",
# "Kickoff next week") are preserved.
# Canonical function-word set shared by classifier (meaningful-fact filter)
# and validator (fallback content anchors) — the two must never diverge:
# a word the classifier treats as non-content must not become a required
# anchor in the validator (Phase 3 benchmark: 'want'/'have'/'after').
CONTENT_STOP = {
    # Words that FLAG a repair are meta-speech about the document, never
    # content in it: a corrected sentence reads "The total budget is
    # $55,000", not "Correction, the total budget is $55,000". Left as
    # content words they became required anchors, so every correction was
    # reported as having dropped its own content and the batch rolled back.
    "correction", "corrections", "sorry", "mistake", "meant", "scratch",
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "at",
    "by", "with", "from", "as", "that", "this", "it", "is", "are", "be",
    "will", "would", "should", "can", "could", "do", "does", "did",
    "our", "their", "his", "her", "its", "we", "they", "you", "i", "he",
    "she", "not", "no", "so", "but", "if", "then", "than", "also", "very",
    "please", "note", "should", "the", "we'll", "we're", "we've",
    # Contractions — a stripped word only trims leading/trailing punctuation,
    # so a mid-word apostrophe (it's, don't) survives as its own token,
    # distinct from the bare form already listed above (it/its). Without
    # these, a contraction becomes a "required" anchor by accident —
    # confirmed live: "it's" forced a real rejection-then-retry cycle that
    # left "It's a website development project." written verbatim into the
    # document, the exact kind of thin sentence this list exists to avoid.
    "it's", "that's", "there's", "here's", "he's", "she's", "what's",
    "let's", "don't", "won't", "can't", "isn't", "aren't", "wasn't",
    "weren't", "didn't", "doesn't", "hasn't", "haven't", "wouldn't",
    "couldn't", "shouldn't", "i'm", "you're", "they're", "i'll", "you'll",
    "they'll", "i've", "you've", "they've", "i'd", "you'd", "they'd",
    "he'd", "she'd",
    # temporal/prepositional words that don't carry fact content
    "after", "before", "during", "once", "later", "soon", "next", "last",
    "month", "year", "day", "first", "second", "third", "another",
    # conversational function words a paraphrase legitimately drops
    "want", "have", "immediately", "like", "really", "just", "maybe",
    "perhaps", "probably", "kind", "sort", "actually", "basically",
    # Modals, auxiliaries and relatives. As required anchors these forced
    # verbatim phrasing: "We NEED a modern responsive website WHERE
    # customers can browse..." rejected an accurate rewrite three times over
    # 'need' and 'where' alone, spending the whole retry budget and leaving
    # Scope of Work blank. Kept in sync with the validator's own _STOP —
    # a word the classifier calls non-content must never become an anchor.
    "need", "needs", "needed", "where", "when", "which", "who", "whom",
    "has", "had", "was", "were", "been", "being", "must", "may", "might",
    "shall", "wants", "expect", "expects", "expected", "there", "here",
    "make", "makes", "made", "set", "begin", "begins", "get", "gets",
    # Conversational words that are not content in ANY template. The
    # validator's own list was tuned to SOW vocabulary, so on Meeting
    # Minutes and Advice Note these became REQUIRED anchors — a proposal
    # was rejected three times for omitting the word "today" out of
    # "Joining us today are Sarah, Mike and Priya". Deliberately no number
    # words here: "three days" carries a value an anchor should keep.
    "us", "them", "him", "me", "my", "your", "today", "tomorrow",
    "yesterday", "because", "while", "since", "about", "into", "over",
    "each", "every", "any", "all", "both", "own", "self", "able", "still",
    "now", "out", "off", "again", "back", "then", "thanks", "morning",
    # Verbs describing the ENGAGEMENT rather than its content. "We are
    # ACTING for Harbour Logistics" puts the client in the details table,
    # where it belongs — but "acting" was then demanded forever after as a
    # required prose anchor, and the preservation check rolled back every
    # later batch for "dropping" it. Same for the other ways a firm states
    # who it is working for.
    "acting", "instructed", "representing", "behalf", "regarding",
    "concerning", "joining", "discuss", "discussing", "walk", "cover",
    # meta-verbs that frame speech without carrying fact content — a
    # paraphrase rewrites "discuss a project" as "the initiative focuses
    # on the project" without losing any fact (minimal_op D evidence)
    "discuss", "talk", "mention", "focus", "focuses", "initiate",
    "initiative", "say", "said", "tell", "ask", "asking", "state",
    "stated", "note", "noted", "cover", "covers", "include",
}


# Meeting-agenda framing ("I'd like to discuss X", "let's talk about X") —
# announces intent to cover a topic, states no fact about it. Forcing this
# into a section makes SuperDocs invent connective business prose to justify
# placing it (observed live: 'enhance', 'initiative', 'presence' fabricated
# to dress up "discuss a website development project" as document content).
# The real facts arrive moments later as the topic is actually discussed.
# Leading greeting/interjection the marker must see past. Real speech opens
# "HI, I'd like to discuss..." — anchoring straight at ^ missed that, the
# opener survived as a fact, and SuperDocs wrote "We will be conducting a
# website development project for Northstar Goods" into Next Steps. That
# stray paragraph then made every legitimate Next Steps edit fail placement
# validation nine times over.
_INTERJECTION = r"(?:(?:hi|hello|hey|okay|ok|so|um|uh|yeah|yep|right|alright)\b[,.]?\s*)*"

_DISCOURSE_MARKER_RE = re.compile(
    rf"^\s*{_INTERJECTION}(?:i'd|i would|i'm|we'd|we would|we're)\s+(?:like|going)\s+to\s+"
    r"(?:discuss|talk about|go over|cover|walk (?:you |everyone )?through)\b"
    rf"|^\s*{_INTERJECTION}(?:let'?s|lets|let us)\s+(?:discuss|talk about|go over|cover)\b"
    rf"|^\s*{_INTERJECTION}(?:i|we)\s+want(?:ed)?\s+to\s+(?:discuss|talk about|go over|cover)\b",
    re.IGNORECASE,
)


# Verbs that assert something about the content word they govern — enough
# to tell a one-word statement from a one-word fragment.
_STATED_VERB_RE = re.compile(
    r"\b(?:need|needs|needed|want|wants|require|requires|include|includes|"
    r"provide|provides|expect|expects|deliver|delivers|add|adds|use|uses|"
    r"is|are|was|were|has|have|had)\b",
    re.IGNORECASE,
)


def _carries_hard_value(text: str) -> bool:
    """True when a sentence states a date or money value — the anchors a
    topic announcement never carries on its own."""
    return bool(
        (_DATE_PRIMARY and any(re.search(p, text, re.IGNORECASE) for p in _DATE_PRIMARY))
        or (_BUDGET_PRIMARY and any(re.search(p, text, re.IGNORECASE) for p in _BUDGET_PRIMARY))
    )


def _is_meaningful_fact(text: str) -> bool:
    """True when the fact carries a recoverable atomic value. Rejects
    fragments like "Our total" / "After launch." while keeping "$45,000",
    "September 15th", "Kickoff next week", and proper-noun entities."""
    t = (text or "").strip()
    if not t or is_filler_only(t):
        return False
    # Date or money anchor — always meaningful.
    if _DATE_PRIMARY and any(re.search(p, t, re.IGNORECASE) for p in _DATE_PRIMARY):
        return True
    if _BUDGET_PRIMARY and any(re.search(p, t, re.IGNORECASE) for p in _BUDGET_PRIMARY):
        return True
    # Proper-noun entity (capitalized multi-word sequence).
    if re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", t):
        return True
    # Enough content words to be a statement. Two content words is a
    # threshold that keeps "Kickoff next week" / "Record the agreement."
    # while dropping "Our total" / "After launch." (one content word).
    words = [w for w in re.split(r"\s+", t) if w.lower() not in CONTENT_STOP and len(w) > 1]
    if len(words) >= 2:
        return True
    # One content word is still a fact when a stated verb governs it: "We
    # need analytics." asserts something, "Our total" / "After launch." do
    # not. Without this, moving the modals into CONTENT_STOP above would
    # silently drop short single-value statements.
    return bool(words) and _STATED_VERB_RE.search(t) is not None

# Explicit old-value markers for corrections: "not September 15th",
# "September 15th, not September 20th", "change it to September 20th".
_EXPLICIT_OLD_VALUE = re.compile(
    r"\bnot\s+([a-zA-Z0-9$][^,.;]{0,40}?)\b(?=[,.;]|$)|"
    r"([a-zA-Z0-9$][^,.;]{0,40}?)\s*[,.]?\s+not\s+(?:the\s+)?(?:same|that)\b",
    re.IGNORECASE,
)

_GROUNDING_PREAMBLE = (
    "SOURCE-GROUNDING RULE: Only add or change facts explicitly stated in the "
    "instruction below. Never invent project names, client names, dates, budgets, "
    "timelines, deliverables, technologies, business objectives, participants, "
    "assumptions, or any other factual content not present in the source transcript."
)

_STRUCTURAL_CONSTRAINTS = (
    "OPERATION CONSTRAINTS:\n"
    "- Only edit the sections listed as targets; place each fact in the section where it belongs.\n"
    "- NEVER modify, merge, or append to section headings (<h2> text) — headings must stay exactly as they are.\n"
    "- NEVER add new rows to existing tables, new columns, or new sections.\n"
    "- NEVER remove, truncate, or rephrase existing content in other sections — add your facts without deleting anything.\n"
    "- NEVER add raw transcript sentences verbatim; write each fact as clean prose.\n"
    "- NEVER invent facts not supported by the source transcript."
)


@dataclass
class StructuredInstruction:
    """Intermediate representation between classification and SuperDocs —
    what the batch *means*, before it becomes an instruction string."""

    operation: str  # "add" | "correct" | "exclude"
    targets: list[tuple[str, list[str]]] = field(default_factory=list)  # (section, facts)
    source_text: str = ""
    correction_find: str | None = None
    correction_replace: str | None = None


def _draft_headings(draft_html: str) -> list[str]:
    """Parse section headings out of the current draft, decoded and
    whitespace-normalized. The draft — not a hardcoded list — is the source
    of truth for what sections exist, so the same rules serve every
    template (SOW, Minutes, Proposal)."""
    return [
        html_module.unescape(re.sub(r"<[^>]+>", "", m)).strip()
        for m in _HEADING_RE.findall(draft_html or "")
        if html_module.unescape(re.sub(r"<[^>]+>", "", m)).strip()
    ]


def _heading_matches(heading: str, substrings: list[str]) -> bool:
    h = heading.lower()
    return any(sub in h for sub in substrings)


def _is_negation_sentence(sentence: str) -> bool:
    return any(re.search(p, sentence, re.IGNORECASE) for p in _OUT_OF_SCOPE_PRIMARY)


def _extract_excluded_item(sentence: str) -> str:
    """Pull the thing being excluded. "Payment integration is not part of the
    scope." → "Payment integration". "The project does not include ongoing
    marketing, SEO, or content creation after launch." → "ongoing marketing,
    SEO, or content creation" (clause cut at 'after')."""
    m = re.search(r"(?:does\s+not\s+include)\s+(.+)", sentence, re.IGNORECASE)
    if m:
        phrase = re.split(r"\s+(?:after|during)\s+", m.group(1), maxsplit=1)[0]
        return phrase.strip()
    m = re.search(
        r"(.+?)\s+(?:is|are)\s+not\s+(?:part\s+of|included\s+in|within)\s+"
        r"(?:the\s+)?(?:scope|project)",
        sentence,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return sentence.strip()


def _normalize_fact(sentence: str) -> str:
    """Strip conversational openers and dead leading words; keep the fact
    body as spoken. Never rewrites content — only edges. Returns "" for a
    fact that reduces to nothing but filler ("Hi."), so it produces zero
    content anchors and is dropped before it reaches SuperDocs."""
    text = sentence.strip()
    prev = None
    while text != prev:  # chain openers: "Hi. I'd like to discuss..." → "discuss..."
        prev = text
        text = _FILLER_OPENERS.sub("", text).strip()
    if is_filler_only(text):
        return ""
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def _route_sentence(sentence: str, headings: list[str]) -> tuple[str | None, str]:
    """Return (section, fact) for one sentence. Negation always wins and
    routes to Out of Scope; otherwise first matched rule wins; no match (or
    no heading) → (None, fact) so the caller falls back to 'most appropriate
    section'. Meaningless fragments return (None, "") so they never become
    document content.

    A rule with PRIMARY anchors requires one to match (high precision). A
    rule with an empty PRIMARY list (Scope of Work, Project — "no
    standalone anchors", by the module's own design comment) is meant to be
    context-guided instead: falling back to CONTEXT patterns is what makes
    that comment true. Before this fallback existed, an empty PRIMARY list
    made `any(... for p in primary)` unsatisfiable for every sentence,
    silently making those two rules permanently unreachable — confirmed
    live: a real "modern responsive website where customers can browse
    products..." utterance never reached Scope of Work, landing under
    Project Details instead via the unconstrained fallback."""
    if _is_negation_sentence(sentence):
        # An exclusion statement is definitionally meaningful — it states
        # what is NOT included. Checked BEFORE the meaningful-fact filter so
        # "Not include SEO." (one content word) still routes to Out of Scope.
        item = _extract_excluded_item(sentence)
        for h in headings:
            if _heading_matches(h, ["out of scope", "exclusion", "not included"]):
                return h, item
        return None, item
    # Checked against the RAW sentence: _normalize_fact strips the opener
    # ("I'd like to discuss X" → "Discuss X"), so a marker test run after
    # normalization can never match. A topic announcement carrying a hard
    # value ("I'd like to discuss the $45,000 budget") still counts as a
    # fact — only the value-free announcement is dropped. The client name in
    # "...project for North Star" is not lost: the table-fill operation
    # reads it from the batch text, not from this fact.
    if _DISCOURSE_MARKER_RE.search(sentence) and not _carries_hard_value(sentence):
        return None, ""
    normalized = _normalize_fact(sentence)
    if not _is_meaningful_fact(normalized):
        return None, ""
    for primary, context, heading_subs in _SECTION_RULES:
        patterns = primary or context
        if not any(re.search(p, sentence, re.IGNORECASE) for p in patterns):
            continue
        for h in headings:
            if _heading_matches(h, heading_subs):
                return h, normalized
    return None, normalized


def _heading_present(draft_html: str, section: str) -> bool:
    return any(h == section for h in _draft_headings(draft_html))


def _preceding_existing_section(draft_html: str, section: str, template_key: str) -> str | None:
    """The nearest section BEFORE `section` in template order that the draft
    already has — the anchor a new heading is positioned after, so sections
    appear in template order however they arrive in conversation."""
    from app.drafting.templates import template_sections

    order = template_sections(template_key)
    if section not in order:
        return None
    live = set(_draft_headings(draft_html))
    for prior in reversed(order[: order.index(section)]):
        if prior in live:
            return prior
    return None


def _routable_headings(draft_html: str, template_key: str = "") -> list[str]:
    """Sections a fact may be routed to: the template's full canonical set,
    plus anything already in the draft.

    Sections are no longer seeded into the starter document — a heading
    appears only when something is said that belongs under it — so routing
    can no longer read the target list off the draft. It comes from the
    template instead, and the draft is merged in so a heading the platform
    has already created is never treated as unknown."""
    live = _draft_headings(draft_html)
    if not template_key:
        return live
    from app.drafting.templates import template_sections

    known = template_sections(template_key)
    return known + [h for h in live if h not in known]


def _norm_value(value: str) -> str:
    """Compare values by their digits and letters alone — "$45,000" and
    "$45,000." and "45000" are the same figure."""
    return re.sub(r"[^0-9a-z]", "", (value or "").lower())


def _section_holding_value(text: str, draft_html: str) -> str | None:
    """Which section currently contains the value this repair replaces?

    A correction has to land where the old value already lives. Routing the
    repair text alone is not enough — "Actually, no, make it $55,000" carries
    no section vocabulary at all, only a figure.
    """
    old_value = _superseded_value_in_draft(text, draft_html)
    if not old_value:
        return None
    needle = old_value.lower()
    for heading in _draft_headings(draft_html):
        body = _section_body(draft_html, heading) or ""
        if needle in _strip_html(body).lower():
            return heading
    return None


def _target_sections(
    text: str, draft_html: str, template_key: str = ""
) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Split the batch into sentences and route each to a section. Returns
    (targets, unmatched_facts) where targets is [(section, [facts]), ...] in
    document order, and unmatched_facts are sentences with no section hit
    (the LLM still gets them, but framed as 'most appropriate section')."""
    headings = _routable_headings(draft_html, template_key)
    sentences = _recover_sentence_boundaries(text)
    by_section: dict[str, list[str]] = {}
    unmatched: list[str] = []
    for sentence in sentences:
        section, fact = _route_sentence(sentence, headings)
        if not fact:
            # Filler-only ("Hi.") — no content, no anchors, never a fact.
            continue
        if section is not None:
            by_section.setdefault(section, []).append(fact)
        else:
            # A fact that matches no section still reaches the document, but
            # the platform decides where it goes — which is how a budget line
            # ended up inside a table cell meant for the date. Log the inputs:
            # every routing hypothesis reproduced correctly in isolation, so
            # the difference has to be in the live headings or the exact fact
            # text, and neither was recorded anywhere.
            logger.warning(
                "UNROUTED fact=%r | headings=%s", fact[:90], headings
            )
            unmatched.append(fact)
    targets = [(s, by_section[s]) for s in by_section if by_section[s]]
    return targets, unmatched


_CORRECTION_CONSTRAINTS = (
    "CORRECTION CONSTRAINTS:\n"
    "- This REPLACES an existing value. Overwrite it in place; do not add a "
    "second sentence alongside the old one.\n"
    "- The old value must NOT survive anywhere in the document.\n"
    "- Change only the sentence containing that value. Leave every other "
    "section exactly as it is.\n"
    "- NEVER modify section headings, add new rows to existing tables, new "
    "columns, or new sections.\n"
    "- NEVER add placeholder text such as 'Please fill:', TBD or TODO.\n"
    "- NEVER invent facts not supported by the source transcript."
)


def _superseded_value_in_draft(text: str, draft_html: str) -> str | None:
    """The value in the document that this correction replaces.

    A repair states the new figure and leaves the old one implied — the
    document is where the old one lives. Matched by KIND (money against
    money, a date against a date) and only when the draft holds exactly one
    candidate of that kind, so an ambiguous document is left alone rather
    than having the wrong sentence rewritten."""
    draft_text = _strip_html(draft_html)
    for pattern in (_MONEY_VALUE_RE, _DATE_VALUE_RE):
        said = {m.group(0).strip() for m in pattern.finditer(text)}
        if not said:
            continue
        said_norm = {v.lower() for v in said}
        have = [
            m.group(0).strip() for m in pattern.finditer(draft_text)
            if m.group(0).strip().lower() not in said_norm
        ]
        unique = list(dict.fromkeys(have))
        if len(unique) == 1:
            return unique[0]
    return None


def correction_values(text: str, draft_html: str) -> tuple[str | None, str | None]:
    """(old, new) for a correction — what leaves the document and what
    replaces it.

    The session previously derived only the old value, and only from an
    explicitly restated one, passing None for the new. validate_correction
    gates its replacement checks on having BOTH, so they never ran: a
    correction was approved without anything verifying the old value was
    actually gone.
    """
    old = _find_explicit_old_value(text) or _superseded_value_in_draft(text, draft_html)
    new = None
    for pattern in (_MONEY_VALUE_RE, _DATE_VALUE_RE):
        said = [m.group(0).strip() for m in pattern.finditer(text)]
        if not said:
            continue
        # The replacement is the value the speaker just stated that is not
        # the one being retired.
        candidates = [v for v in said if not old or v.lower() != old.lower()]
        if candidates:
            new = candidates[-1]
            break
    return old, new


def _find_explicit_old_value(text: str) -> str | None:
    """Best-effort extraction of the value being replaced, when the speaker
    named it explicitly ("not September 15th"). Returns None when the old
    value is only implied — the instruction then targets the section and
    lets the LLM locate the value there."""
    # A comma ends the value ONLY when it is not a thousands separator.
    # Excluding every comma made "not $45,000." capture "$45": the old value
    # then matched nothing in the draft, and the replacement was computed as
    # the value that was not "$45" — which is "$45,000", the very figure
    # being retired. The instruction became "replace $45 with $45,000", so
    # the correction deleted the old amount and never wrote the new one.
    # Live, Budget was left empty by a correction that had both figures.
    for pat in (
        r"not\s+([a-zA-Z0-9$][^.;]{0,40}?)(?=[.;]|,\s*(?!\d)|$)",
        r"(?:from|replace)\s+([a-zA-Z0-9$][^.;]{0,40}?)\s+to\s+",
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def build_structured_instruction(
    classification: str,
    text: str,
    draft_html: str,
    template_key: str,
) -> str:
    """Build a section-targeted, structurally-constrained instruction for
    SuperDocs. The downstream LLM still performs the edit, but its search
    space is deliberately constrained: it is told which existing sections
    may change, which values to find/replace on a correction, and that
    headings/table structure are off-limits.

    Falls back to the unconstrained path when nothing matches (unmatched
    sentences route to 'most appropriate section'), so the structured layer
    can only narrow, never drop content."""

    targets, unmatched = _target_sections(text, draft_html, template_key)

    if classification == CORRECTION:
        lines = [_GROUNDING_PREAMBLE, "", "Correct a value in the document:"]
        # The speaker rarely restates what they are replacing — "actually,
        # make it $55,000" names only the new figure. Falling back to the
        # superseded value the DOCUMENT already holds is what makes the
        # replacement addressable; without it the instruction said "replace
        # with $55,000" while naming nothing to replace, and the live run
        # left $45,000 standing.
        find = _find_explicit_old_value(text) or _superseded_value_in_draft(text, draft_html)
        if find:
            lines.append(f'FIND: "{find}"')
            lines.append(f'That exact text is already in the document. Replace it IN PLACE.')
        lines.append(f"REPLACE WITH the value stated in: \"{text}\"")
        if targets:
            sections = ", ".join(s for s, _ in targets)
            lines.append(f"IN SECTION: {sections}")
        else:
            lines.append("IN SECTION: the section of the document that contains the value being corrected")
        # Deliberately NOT _STRUCTURAL_CONSTRAINTS: that block ends with
        # "add your facts without deleting anything", which forbids the one
        # thing a correction exists to do. A repair must overwrite.
        lines += ["", _CORRECTION_CONSTRAINTS]
        return "\n".join(lines)

    # Exclude / addition paths.
    if targets:
        lines = [_GROUNDING_PREAMBLE, "", "Add facts to the following sections of the document:"]
        for section, facts in targets:
            lines.append("")
            lines.append(f"[Target: {section}]")
            for fact in facts:
                lines.append(f"- {fact}")
    else:
        lines = [_GROUNDING_PREAMBLE, "", "Add facts to the most appropriate section of the document:"]
    if unmatched:
        lines.append("")
        lines.append("[Target: most appropriate section]")
        for fact in unmatched:
            lines.append(f"- {fact}")
    lines.append("")
    lines.append(f"Source transcript: \"{text}\"")
    lines.append("")
    lines.append(_STRUCTURAL_CONSTRAINTS)
    return "\n".join(lines)


def _single_section_instruction(
    section: str, facts: list[str], source_text: str, draft_html: str = "",
    template_key: str = "",
) -> str:
    """One bounded instruction for ONE section — the exact format the
    single-target diagnostic proved SuperDocs reliably obeys ([Target: X]
    header, one section, structural constraints). The downstream LLM edits
    only this section; every fact in the batch that belongs here is listed
    explicitly, nothing else appears as a target."""
    lines = [
        _GROUNDING_PREAMBLE,
        "",
        "Add the following facts to the document:",
        "",
        f"[Target: {section}]",
        "",
    ]
    if _heading_present(draft_html, section):
        lines.append(
            "The section heading already exists in the document — add content ONLY. "
            "Never include or repeat heading markup in the edit."
        )
    else:
        # Sections are not seeded any more; the first fact that belongs
        # under a heading is what brings the heading into existence, so the
        # document grows with the conversation instead of opening as a wall
        # of empty subheadings.
        after = _preceding_existing_section(draft_html, section, template_key)
        where = f" immediately after the '{after}' section" if after else " at the end of the document"
        lines.append(
            f"This section does not exist yet. Create the heading '{section}' "
            f"as an h2{where}, then put the content under it. Create that ONE "
            f"heading only — never any other heading, and never alter an existing one."
        )
    # Naming the heading's chunk id here was tried and removed. It did not
    # stop the "outside section" rejections — SuperDocs anchored where it
    # liked regardless — and it actively caused new ones: pointed at the
    # heading's chunk, SuperDocs returned the heading together with the new
    # text, which the gate then rejected as "proposal contains heading
    # markup". Placement is verified after the edit instead, against the
    # resulting HTML, which is the only check the platform can satisfy.
    for fact in facts:
        lines.append(f"- {fact}")
    lines.append("")
    lines.append(f"Source transcript: \"{source_text}\"")
    lines.append("")
    lines.append(_STRUCTURAL_CONSTRAINTS)
    return "\n".join(lines)


def _unmatched_section_instruction(facts: list[str], source_text: str) -> str:
    """Fallback instruction for facts no rule could route — the LLM picks
    the best existing section, with the same structural constraints. Never
    drops content: unmatched facts always reach the document."""
    lines = [
        _GROUNDING_PREAMBLE,
        "",
        "Add the following facts to the most appropriate section of the document:",
        "",
    ]
    for fact in facts:
        lines.append(f"- {fact}")
    lines.append("")
    lines.append(f"Source transcript: \"{source_text}\"")
    lines.append("")
    lines.append(_STRUCTURAL_CONSTRAINTS)
    return "\n".join(lines)


def build_section_instructions(
    classification: str,
    text: str,
    draft_html: str,
    template_key: str,
) -> list[str]:
    """Split one transcript batch into a list of bounded instructions — one
    per target section, in the order the sections appear in the live draft
    (never arbitrary dict order). Each instruction targets exactly one
    section; unmatched facts form one trailing 'most appropriate section'
    instruction so nothing is dropped.

    Corrections deliberately stay single-instruction for now: correction
    targeting is not redesigned in this phase, and a correction already
    travels as one bounded instruction (IN SECTION + optional FIND)."""
    if classification == CORRECTION:
        return [build_structured_instruction(classification, text, draft_html, template_key)]

    targets, unmatched = _target_sections(text, draft_html, template_key)
    if not targets and not unmatched:
        return []  # filler-only batch — nothing to edit, no SuperDocs call
    if not targets:
        # No section matched — preserve the existing single unconstrained
        # instruction (which routes via 'most appropriate section').
        return [build_structured_instruction(classification, text, draft_html, template_key)]

    # Order targets by their position in the live draft, not by first
    # appearance in the transcript.
    headings = _draft_headings(draft_html)
    targets.sort(key=lambda t: headings.index(t[0]) if t[0] in headings else len(headings))

    instructions = [
        _single_section_instruction(section, facts, text, draft_html, template_key)
        for section, facts in targets
    ]
    if unmatched:
        instructions.append(_unmatched_section_instruction(unmatched, text))
    return instructions


# ---------------------------------------------------------------------------
# Project Details table fill (Client) — Phase B fix
# ---------------------------------------------------------------------------
#
# The Client/Project/Prepared-by cells were structurally unfillable: no
# operation ever targeted them (section-body routing only ever inserts a
# <p>/<div> after a heading, never into a table cell), and the structural
# constraints sent with every other instruction explicitly forbid touching
# tables at all. Confirmed live: "Northstar" was said in the meeting's first
# sentence and the exported document's Client field stayed blank regardless.
# Deliberately narrow — false negatives (missing the fill) are safe; false
# positives (writing the wrong name into Client) are not. Only fires on an
# explicit naming pattern, never a bare capitalized word, and only once
# (while the cell is still empty).

_CLIENT_NAME_PATTERNS = [
    r"\bproject\s+for\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b",
    r"\bclient\s+is\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b",
    r"\bworking\s+with\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b",
    r"\bfor\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})[.,]",
    # bare declarative intro: "North Star Goods is a small e-commerce company"
    r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\s+is\s+an?\s+\w",
    # Advisory / professional-services phrasing.
    r"\b(?:[Oo]ur|[Tt]he)\s+client[,:]?\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b",
    r"\b[Aa]cting\s+for\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b",
    r"\b[Oo]n\s+behalf\s+of\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b",
    r"\b[Ii]nstructed\s+by\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b",
]

_MONTHS_TITLE = {m.capitalize() for m in _MONTHS.split("|")}
_LEADING_WORD_STOP = {"This", "That", "It", "There", "Here", "We", "They", "He", "She", "You"}

# Read the details table generically. The template starts as bare
# <tr><td><strong>Client</strong></td><td></td></tr>, but once SuperDocs has
# edited it the same row is <td colspan="1" rowspan="1"><p><strong>Client
# </strong></p></td>. A pattern pinned to the pristine shape stops matching
# at exactly that point, the cell reads as "not empty" because the lookup
# found no row at all, and a cell that failed to fill once can never be
# filled again.
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)


def _detail_rows(draft_html: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for row in _ROW_RE.findall(draft_html or ""):
        cells = [
            html_module.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
            for c in _CELL_RE.findall(row)
        ]
        if len(cells) >= 2:
            rows.append((cells[0], cells[1]))
    return rows


def _detail_cell(draft_html: str, labels: tuple[str, ...]) -> tuple[bool, str, str]:
    """(row-found, matched-label, current-value) for the first row whose
    label matches. Label varies by template — Project / Matter / Topic."""
    for label, value in _detail_rows(draft_html):
        for want in labels:
            if label.strip().lower() == want.lower():
                return True, label.strip(), value
    return False, "", ""

# "a website development project", "the CRM migration project" — the
# descriptor people actually say when naming what the work is.
_PROJECT_NAME_PATTERNS = [
    # Only the "a/the <descriptor> project" form. A "project is <X>" pattern
    # was tried and removed: it has no right-hand boundary, so it swallowed
    # whatever followed — "the whole project is this" produced the cell value
    # "This", and "the project is this website for North Star" produced
    # "This Website For North". Confirmed live: a real document shipped with
    # Project set to "This".
    r"\b(?:a|an|the|this)\s+([a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,3})\s+project\b",
    # Meeting Minutes call the same cell "Topic"; Advice Notes call it
    # "Matter". Neither says the word "project", so the cell stayed empty
    # in every non-SOW document.
    r"(?i)\btoday(?:'s)?\s+(?:topic|agenda)\s+is\s+(?:the\s+)?([A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9][A-Za-z0-9-]*){0,3})\b",
    r"(?i)\b(?:the\s+)?(?:matter|topic)\s+(?:is|concerns|relates to)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9][A-Za-z0-9-]*){0,3})\b",
    r"(?i)\b(?:regarding|concerning|in relation to)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9][A-Za-z0-9-]*){0,3})\b",
    r"(?i)\bwe(?:'re| are)\s+here\s+to\s+discuss\s+(?:the\s+)?([A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9][A-Za-z0-9-]*){0,3})\b",
]


def _details_heading(draft_html: str) -> str | None:
    """The heading of the section that actually owns the metadata table.

    Named "Project Details" in our Statement of Work, "Matter Details" in an
    Advice Note — and in a firm's own uploaded template, anything at all
    ("Client & Matter"). Matching on the word "details" and otherwise
    falling back to the literal string "Project Details" meant a firm
    template got an operation aimed at a section it does not contain: the
    placement check failed, the batch rolled back, and a live run drafted
    nothing at all from five utterances. The table itself is the reliable
    landmark, so find the heading whose section contains it.
    """
    for heading in _draft_headings(draft_html):
        if "<table" in _section_body(draft_html, heading).lower():
            return heading
    return next((h for h in _draft_headings(draft_html) if "details" in h.lower()), None)


def _section_body(draft_html: str, heading: str) -> str:
    """Everything between a heading and the next one."""
    pattern = re.escape(heading.replace("&", "&amp;"))
    m = re.search(
        rf"<h2[^>]*>[^<]*{pattern}[^<]*</h2>(.*?)(?=<h[12][^>]*>|$)",
        draft_html or "", re.IGNORECASE | re.DOTALL,
    )
    return m.group(1) if m else ""


def _client_cell_is_empty(draft_html: str) -> bool:
    """Whether the Project Details table's Client cell has never been
    filled. No table → nothing to fill (non-SOW templates), treated as
    'not empty' so the fill is never attempted."""
    found, _, value = _detail_cell(draft_html, ("Client",))
    return found and not value.strip()


def _extract_client_name(text: str) -> str | None:
    """Best-effort extraction of a client/company name from an early
    addition batch — 'for Northstar', 'client is Acme Corp'."""
    for pattern in _CLIENT_NAME_PATTERNS:
        m = re.search(pattern, text)
        if m:
            name = m.group(1).strip()
            if name and name not in _MONTHS_TITLE and name.split()[0] not in _LEADING_WORD_STOP:
                return name
    return None


def _project_cell_is_empty(draft_html: str) -> tuple[bool, str]:
    """(is-empty, row-label) for the details table's Project/Matter/Topic
    row. Row label varies by template, so it is read from the draft rather
    than assumed."""
    found, label, value = _detail_cell(draft_html, ("Project", "Matter", "Topic"))
    if not found:
        return False, ""
    return (not value.strip()), label


def _extract_project_name(text: str) -> str | None:
    """The project descriptor as spoken — "a website development project"
    yields "Website Development". Title-cased because it labels a table
    cell, not prose."""
    for pattern in _PROJECT_NAME_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).split()
            if any(w.lower() in _PROJECT_NAME_REJECT for w in raw):
                continue
            words = [w for w in raw if w.lower() not in _PROJECT_NAME_STOP]
            if words:
                # str.title() would turn "CRM" into "Crm" — an acronym the
                # speaker said in full caps stays as spoken.
                return " ".join(w if w.isupper() else w.capitalize() for w in words)
    return None


_PROJECT_NAME_STOP = {
    "new", "whole", "entire", "small", "big", "our", "your", "their",
    # Pronouns and determiners are never a project name on their own.
    "this", "that", "it", "one", "same", "current", "said", "the", "a", "an",
    "is", "are", "was", "were", "be",
}

# A project name is a noun phrase. A preposition means the match ran past
# the end of the name and swallowed the next clause.
_PROJECT_NAME_REJECT = {"for", "of", "in", "on", "with", "to", "from", "at", "by", "and", "or"}


def _table_fill_instruction(field: str, value: str) -> str:
    lines = [
        _GROUNDING_PREAMBLE,
        "",
        "Fill in ONE empty cell of the EXISTING Project Details table.",
        f"Change the '{field}' row's value cell from empty to exactly: {value}",
        "",
        "TABLE CONSTRAINTS:",
        "- Do not add, remove, or reorder any table row.",
        "- Do not change the value of any OTHER row in this table.",
        "- Do not add a new table, new columns, or any paragraph text outside the table.",
        f"- Change only the '{field}' row's empty value cell.",
    ]
    return "\n".join(lines)


def _client_fill_operation(text: str, draft_html: str) -> "SectionOperation | None":
    """Returns a table-fill operation when this addition batch names a
    client and the Client cell is still empty, else None. The details
    table's own heading isn't always "Project Details" — Advice Note calls
    it "Matter Details", Meeting Minutes calls it "Meeting Details" — so
    the target is whichever heading actually contains the word "details",
    not a hardcoded name (a hardcoded target that doesn't exist in the
    live draft is exactly the failure already observed live: SuperDocs
    reporting it "couldn't find" a named section)."""
    if not _client_cell_is_empty(draft_html):
        return None
    name = _extract_client_name(text)
    if not name:
        return None
    details_heading = _details_heading(draft_html)
    if details_heading is None:
        return None
    return SectionOperation(
        instruction=_table_fill_instruction("Client", name),
        section=details_heading,
        facts=[name],
        table_field="Client",
        table_value=name,
    )


def _project_fill_operation(text: str, draft_html: str) -> "SectionOperation | None":
    """The Project/Matter row's counterpart to _client_fill_operation."""
    empty, label = _project_cell_is_empty(draft_html)
    if not empty:
        return None
    name = _extract_project_name(text)
    if not name:
        return None
    details_heading = _details_heading(draft_html)
    if details_heading is None:
        return None
    return SectionOperation(
        instruction=_table_fill_instruction(label, name),
        section=details_heading,
        facts=[name],
        table_field=label,
        table_value=name,
    )


@dataclass
class SectionOperation:
    """One bounded document operation: the instruction sent to SuperDocs,
    the section it must touch, and the exact facts it must carry. The HITL
    validator uses `section` and `facts` as ground truth for the gate."""

    instruction: str
    section: str | None  # None → "most appropriate section" fallback
    facts: list[str]
    # True only for the operation that repairs a value. A batch is
    # classified a correction when ANY sentence repairs something, but the
    # rest of that batch is ordinary new information split out into normal
    # ops — and those must not be judged by the correction validator, which
    # requires an "edit" operation and rejects a plain insertion as
    # "correction proposal is not an edit operation".
    is_correction: bool = False
    # Set only for a Project Details table-cell fill (Client/Project) — the
    # gate validates these completely differently from a section-body edit
    # (row/column count must stay identical; only this one cell's value may
    # change), so the validator needs to know which shape it's checking.
    table_field: str | None = None
    table_value: str | None = None


def _section_targeting_enabled() -> bool:
    """Read at call time, not import time, so tests can flip it."""
    try:
        from app.core.config import get_settings

        return bool(get_settings().section_targeting)
    except Exception:
        return True


def build_section_operations(
    classification: str,
    text: str,
    draft_html: str,
    template_key: str,
) -> list[SectionOperation]:
    """Like build_section_instructions, but returns the structured form —
    instruction plus the intended target section and expected facts — so
    the validation gate can check proposed changes against ground truth
    rather than trusting the model's own explanation."""
    if classification == CORRECTION:
        # A batch is classified a correction when ANY sentence repairs a
        # value, but the rest of the batch is usually ordinary new
        # information — "Actually, no, make it $55,000. The deliverables
        # should include the website." One correction op for the whole
        # batch handed that deliverables sentence to a FIND/REPLACE
        # instruction, which knows only how to swap a value: the budget was
        # left unchanged AND Deliverables came out empty, from one batch.
        # Split it — the repair gets a correction op, everything else goes
        # through the normal addition path.
        sentences = [x for x in _SENTENCE_SPLIT.split(text) if x.strip()]
        sentences = _merge_cue_only(sentences)
        repair = [x for x in sentences if has_correction_cue(x)]
        rest = [x for x in sentences if not has_correction_cue(x)]
        # The caller already decided this batch is a correction. When no
        # single sentence carries a cue — because resolve_intra_batch_correction
        # stripped the bare "Correction." marker before we got here — the
        # repair is the sentence whose value the document ALREADY holds.
        # That is what a repair is: a replacement for something present.
        #
        # Treating the whole batch as the repair instead collapsed every
        # sentence into one operation aimed at a single section. Live:
        #
        #   BATCH ROUTED: 'the 30th. Our total budget is $55,000.'
        #                 -> ops=['Timeline & Milestones']
        #
        # "30th" was already in Timeline, so the batch aimed there and the
        # budget sentence went with it. Budget / Commercial Terms was left
        # empty, and because no operation ever targeted it, nothing was
        # owed and nothing was in the ledger — reconciliation had no idea
        # the figure was missing.
        #
        # Sentences the document does NOT already hold are new information
        # and go through the ordinary addition path, exactly as they would
        # if a cue had survived. `rest` must still never overlap `repair`,
        # or one utterance produces two competing edits.
        if not repair:
            held = [x for x in sentences if _section_holding_value(x, draft_html) is not None]
            if held:
                repair = held
                rest = [x for x in sentences if x not in held]
            else:
                # No cue survived AND nothing here replaces a value the
                # document already holds — so there is no repair in this
                # batch at all; the cue belonged to an earlier one. Route
                # the whole thing as ordinary new information, which sends
                # each sentence to its OWN section. Delegating entirely
                # (rather than emitting a correction op as well) is what
                # keeps one utterance from producing two competing edits.
                return build_section_operations(
                    ADDITION, text, draft_html, template_key
                )

        repair_text = " ".join(repair) or text
        facts = [f for f in (_normalize_fact(x) for x in (repair or sentences)) if f]
        if not facts:
            return []  # filler-only correction — nothing to correct
        # Aim the correction at a section. Left as None, the platform decides
        # placement — and live it put a corrected budget figure inside the
        # Project Details table cell meant for the document date, while the
        # Budget section stayed empty. A correction belongs in the section that
        # holds the value being corrected; failing that, wherever the repair
        # text routes on its own. Only if neither resolves does the platform
        # choose, and then placement cannot be checked either.
        # A repair that replaces a value with itself is not a repair. Whisper
        # mis-hears the corrected figure often enough that this is a real case,
        # not a theoretical one: "Our total budget $45,000. no, make it
        # $45,000." reached the API as a correction, the platform answered with
        # an insert rather than an edit (there being nothing to change), and the
        # gate spent three attempts refusing it before surfacing
        # "correction proposal is not an edit operation" to the reviewer.
        target = _section_holding_value(repair_text, draft_html)
        if target is None:
            routed, _unmatched = _target_sections(repair_text, draft_html, template_key)
            target = routed[0][0] if routed else None

        # A repair that asks for the value already in the document is not a
        # repair. Whisper mis-hears the corrected figure often enough that this
        # is a real case: "Our total budget $45,000. no, make it $45,000."
        # reached the API as a correction, the platform answered with an insert
        # rather than an edit — there being nothing to change — and the gate
        # spent three attempts refusing it before telling the reviewer
        # "correction proposal is not an edit operation".
        _, new_value = correction_values(repair_text, draft_html)
        if new_value and target:
            current = _strip_html(_section_body(draft_html, target) or "")
            if _norm_value(new_value) and _norm_value(new_value) in _norm_value(current):
                return build_section_operations(
                    ADDITION, text, draft_html, template_key
                )
        ops = [
            SectionOperation(
                instruction=build_structured_instruction(
                    classification, repair_text, draft_html, template_key
                ),
                section=target,
                facts=facts,
                is_correction=True,
            )
        ]
        if rest:
            ops.extend(
                build_section_operations(ADDITION, " ".join(rest), draft_html, template_key)
            )
        return ops

    targets, unmatched = _target_sections(text, draft_html, template_key)
    if not _section_targeting_enabled():
        # Section targeting off: the platform decides placement. Facts are
        # still extracted, cleaned and gated exactly as before — only the
        # "[Target: X]" header and the per-section split are dropped, so a
        # batch becomes one instruction naming no heading at all.
        every_fact = [f for _, facts in targets for f in facts] + list(unmatched)
        untargeted: list[SectionOperation] = []
        if every_fact:
            untargeted.append(
                SectionOperation(
                    instruction=_unmatched_section_instruction(every_fact, text),
                    section=None,
                    facts=every_fact,
                )
            )
        for fill in (
            _client_fill_operation(text, draft_html),
            _project_fill_operation(text, draft_html),
        ):
            if fill is not None:
                untargeted.append(fill)
        return untargeted

    if not targets and not unmatched:
        # No prose to write — but a pure topic announcement ("Hi, I'd like
        # to discuss a website project for Northstar Goods.") still names
        # the client, and that belongs in the table even though the
        # sentence itself is not document content.
        table_ops = [
            op
            for op in (
                _client_fill_operation(text, draft_html),
                _project_fill_operation(text, draft_html),
            )
            if op is not None
        ]
        return table_ops

    if not targets:
        ops = [
            SectionOperation(
                instruction=_unmatched_section_instruction(unmatched, text),
                section=None,
                facts=unmatched,
            )
        ]
    else:
        headings = _routable_headings(draft_html, template_key)
        targets.sort(key=lambda t: headings.index(t[0]) if t[0] in headings else len(headings))

        ops = [
            SectionOperation(_single_section_instruction(s, f, text, draft_html, template_key), s, f)
            for s, f in targets
        ]
        if unmatched:
            ops.append(SectionOperation(_unmatched_section_instruction(unmatched, text), None, unmatched))

    # Table fill runs alongside the normal section operations, not instead
    # of them — a batch can both name the client AND carry other facts.
    client_op = _client_fill_operation(text, draft_html)
    if client_op is not None:
        ops.append(client_op)
    project_op = _project_fill_operation(text, draft_html)
    if project_op is not None:
        ops.append(project_op)
    return ops
