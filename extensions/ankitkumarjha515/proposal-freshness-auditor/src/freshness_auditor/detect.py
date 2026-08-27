"""The detection engine: find STALE fact claims in a proposal document.

A claim is stale when it states a value the ledger has **retired**
(`Fact.prior_values`). The engine's headline capability is that it finds
*paraphrased* stale claims — "twelve hundred staff members" for a retired
headcount of 1200, "03/2023" for a retired renewal date of "March 2023" —
not merely character-identical copies.

The rule, in one sentence
-------------------------
A span is flagged only when BOTH hold:

1. the span's canonical value equals one of the fact's **retired** values
   (never its current value), and
2. at least one **subject term** of that same fact appears in the same
   sentence.

Condition 2 is the false-positive killer, and it is doing three separate
jobs at once:

* `"1,200 laptops were distributed"` carries the retired headcount number
  but no headcount subject term, so it is not a finding.
* `find_numbers("ISO 9001")` legitimately reports the number 9001 —
  that is correct at the normalization layer, which cannot know what 9001
  means. Here, 9001 can only ever become a finding if a fact actually
  retired the value 9001 *and* one of that fact's subject terms sits in
  the same sentence. No denylist of strings is involved, and none is
  wanted: a denylist would be document-content special-casing, and it
  would still be wrong the first time a real client had 9001 employees.
* the same mechanism disarms bare number-words that are also ordinary
  words — `"One Health initiative"` (1.0), `"Four Seasons"` (4.0). They
  are numbers; they are simply never near a subject term.

Word order does not matter: `"across 14 countries we work"` and
`"countries of operation: 14"` are both findings, because condition 2 is
a set membership test over the sentence, not a template.

What is data and what is code
-----------------------------
Every fact value, synonym, and unit comes from the ledger YAML. The only
tables in this module are linguistic, not document-specific: English
function words (`STOPWORDS`), historical/negation marker phrases, hedge
prefixes, HTML block tags, and the confidence weights. Adding a synonym,
a fact, or a unit is a data edit in `facts.yaml`; teaching the detector a
new hedge word or historical marker is an edit to one tuple here. No
string from any fixture document appears in this file.

Documents are data, never instructions. Nothing in this module inspects
document text for commands, and no control flow depends on what a
document *says* — only on whether values and subject terms are present.
The prompt-injection fixture is processed by exactly the same code path
as inert prose.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

from .ledger import Fact, FactLedger, PriorValue
from .normalize import find_month_years, find_numbers, values_equivalent

__all__ = [
    "Block",
    "Evidence",
    "Finding",
    "BLOCK_TAGS",
    "STOPWORDS",
    "HISTORICAL_MARKERS",
    "NEGATION_MARKERS",
    "HEDGE_PREFIXES",
    "CONFIDENCE_WEIGHTS",
    "parse_blocks",
    "document_text",
    "split_sentences",
    "subject_terms",
    "detect",
    "detect_all",
]


# ---------------------------------------------------------------------------
# Public data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """Everything a human needs to check a finding without trusting us."""

    sentence: str  # the full enclosing sentence, for human review
    quote: str  # the matched span, exactly as written
    start: int  # char offset into `document_text(html)`
    end: int
    chunk_id: str | None  # data-chunk-id of the enclosing element, if any
    element_index: int  # ordinal position of the enclosing block element


@dataclass(frozen=True)
class Finding:
    """One stale claim.

    `matched_prior` is an addition to the shape given in the task brief.
    `Fact.prior_values` is a list, so a fact can carry several generations
    of a retired figure; a finding that did not say *which* one it matched
    would leave a reviewer unable to tell a two-year-old copy from a
    six-year-old one. Everything before it keeps the brief's field order,
    so positional construction of the brief's fields still works.
    """

    id: str  # deterministic: stable hash of (doc_id, fact_id, start, end)
    fact_id: str
    doc_id: str
    match_type: str  # "exact" | "paraphrase"
    stated_value: str  # what the document says, as written
    canonical_value: str  # what the ledger says it should be
    source: str  # the fact's provenance
    as_of: date  # the fact's date
    confidence: float  # 0.0-1.0
    evidence: Evidence
    matched_prior: PriorValue  # WHICH retired value this claim restates


@dataclass(frozen=True)
class Block:
    """One block-level element's text, positioned in the document text."""

    text: str  # whitespace-normalised text of the element
    chunk_id: str | None
    element_index: int
    offset: int  # start of `text` within `document_text(html)`
    tag: str  # "" for text that sat outside any block element


# ---------------------------------------------------------------------------
# Module-level data tables. Linguistic only — extend these, not the logic.
# ---------------------------------------------------------------------------

# Block-level elements whose text is extracted separately. SuperDocs adds
# `data-chunk-id` to these on upload; local fixtures may not carry one.
BLOCK_TAGS: frozenset[str] = frozenset(
    {"h1", "h2", "h3", "h4", "h5", "h6", "p", "tr", "li"}
)

# Table cells: not blocks themselves (a ROW is the unit of meaning,
# since the label sits in one cell and the value in the next), but their
# boundaries still need a separator.
CELL_TAGS: frozenset[str] = frozenset({"td", "th"})

# Elements whose text content is never prose.
SKIP_TAGS: frozenset[str] = frozenset({"script", "style"})

# English function words. Stripped from a fact's subject/synonym phrases so
# that "countries of operation" contributes the terms {countries, operation}
# and not the term "of" (which would match every sentence ever written).
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "by", "for",
        "from", "has", "have", "in", "is", "it", "its", "of", "on", "or",
        "our", "per", "that", "the", "their", "this", "to", "was", "we",
        "were", "with",
    }
)

# Phrases that mark a sentence as possibly a legitimate *historical*
# statement rather than a stale claim ("we previously employed 1,200
# staff"). These lower confidence; they NEVER suppress a finding, because
# surfacing at low confidence beats silently dropping.
HISTORICAL_MARKERS: tuple[str, ...] = (
    "previously", "formerly", "historically", "in the past", "at the time",
    "at that time", "used to", "prior to", "back in", "up until",
    "no longer", "as of", "superseded", "since retired", "then-current",
)

# Negation words: a negated sentence may be denying the stale value.
NEGATION_MARKERS: tuple[str, ...] = (
    "not", "never", "neither", "nor", "cannot", "isn't", "aren't", "wasn't",
    "weren't", "doesn't", "don't",
)

# Hedge prefixes recognised immediately before a *month-year* span. Numeric
# spans already carry their hedge on `NumberMatch.hedge`; month-year spans
# have no hedge field, so the enclosing sentence is checked instead.
HEDGE_PREFIXES: tuple[str, ...] = (
    "approximately", "around", "about", "roughly", "circa", "on or about",
    "sometime in", "~",
)

# Confidence weights. See `_confidence` for the formula that consumes them.
CONFIDENCE_WEIGHTS: dict[str, float] = {
    "base_exact": 0.95,
    "base_paraphrase": 0.85,
    "distance_penalty_per_char": 0.0005,
    "max_distance_penalty": 0.15,
    "hedge_penalty": 0.10,
    "partial_subject_penalty": 0.10,
    "counted_noun_mismatch_penalty": 0.15,
    "historical_marker_penalty": 0.45,
    "negation_penalty": 0.25,
    "current_value_in_sentence_penalty": 0.20,
    "floor": 0.05,
}


def _phrase_alternation(phrases: tuple[str, ...]) -> str:
    """Build a word-boundary alternation from a table of marker phrases,
    tolerating any run of whitespace inside a multi-word phrase."""
    return "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in phrases)


_HISTORICAL_RE = re.compile(
    r"\b(?:" + _phrase_alternation(HISTORICAL_MARKERS) + r")\b", re.IGNORECASE
)
_NEGATION_RE = re.compile(
    r"\b(?:" + _phrase_alternation(NEGATION_MARKERS) + r")\b", re.IGNORECASE
)
# A hedge phrase, then at most two intervening words, then the span start.
_HEDGE_BEFORE_RE = re.compile(
    r"(?:" + _phrase_alternation(HEDGE_PREFIXES) + r")\W*(?:\w+\W+){0,2}$",
    re.IGNORECASE,
)
_HEDGE_LOOKBACK_CHARS = 60

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_WHITESPACE_RE = re.compile(r"\s+")
# A sentence ends at .!? followed by whitespace. The lookbehind means a
# decimal point ("3.2 million") never splits a sentence, because the
# character after it is a digit, not whitespace.
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])["\'\)\]]*\s+')


# ---------------------------------------------------------------------------
# HTML -> blocks of plain text
# ---------------------------------------------------------------------------


def _normalise_ws(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


class _BlockExtractor(HTMLParser):
    """Collects the text of each block-level element, in document order.

    Text that sits outside any block element (including a caller that
    passed plain text rather than HTML) is emitted as its own block with
    `tag == ""`, so `detect` works uniformly on both.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.text: str = ""
        self._stack: list[list] = []  # [tag, chunk_id, buffer]
        self._loose: list[str] = []
        self._chunk_stack: list[tuple[str, str]] = []
        self._skip_depth = 0

    # -- emission ---------------------------------------------------------
    def _emit(self, raw: str, chunk_id: str | None, tag: str) -> None:
        content = _normalise_ws(raw)
        if not content:
            return
        if self.text:
            self.text += "\n"
        offset = len(self.text)
        self.text += content
        self.blocks.append(
            Block(
                text=content,
                chunk_id=chunk_id,
                element_index=len(self.blocks),
                offset=offset,
                tag=tag,
            )
        )

    def _flush_loose(self) -> None:
        if not self._loose:
            return
        raw = "".join(self._loose)
        self._loose = []
        self._emit(raw, None, "")

    def _flush_open_partial(self) -> None:
        """A block element opened inside another one: emit what the outer
        element has accumulated so far, so document order is preserved."""
        if not self._stack:
            return
        tag, chunk_id, buf = self._stack[-1]
        self._emit("".join(buf), chunk_id, tag)
        buf.clear()

    # -- HTMLParser hooks -------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "br":
            self._append(" ")
            return

        own_chunk = None
        for name, value in attrs:
            if name.lower() == "data-chunk-id":
                own_chunk = value
        if own_chunk is not None:
            # Chunk ids live on whatever element the server chose — often a
            # container like <ul> or <table>, not the <li> or <tr> inside it.
            # Tracking every one lets an inner block inherit the id of the
            # chunk it actually belongs to, which is what the apply stage
            # needs to say "this is the chunk I meant to change".
            self._chunk_stack.append((tag, own_chunk))

        if tag in BLOCK_TAGS:
            self._flush_loose()
            self._flush_open_partial()
            chunk_id = own_chunk
            if chunk_id is None and self._chunk_stack:
                chunk_id = self._chunk_stack[-1][1]
            self._stack.append([tag, chunk_id, []])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        for i in range(len(self._chunk_stack) - 1, -1, -1):
            if self._chunk_stack[i][0] == tag:
                del self._chunk_stack[i:]
                break
        if tag in CELL_TAGS:
            # A row is one block, so its cells run together. Separate them,
            # or "Total permanent staff" + "1,200" becomes "staff1,200" and
            # the subject term is destroyed.
            self._append(" ")
            return
        if tag not in BLOCK_TAGS:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                while len(self._stack) > i:
                    open_tag, chunk_id, buf = self._stack.pop()
                    self._emit("".join(buf), chunk_id, open_tag)
                return

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._append(data)

    def _append(self, data: str) -> None:
        if self._stack:
            self._stack[-1][2].append(data)
        else:
            self._loose.append(data)

    def finish(self) -> None:
        while self._stack:
            open_tag, chunk_id, buf = self._stack.pop()
            self._emit("".join(buf), chunk_id, open_tag)
        self._flush_loose()


def parse_blocks(html_or_text: str) -> tuple[str, list[Block]]:
    """Split a document into block-level chunks of whitespace-normalised text.

    Returns `(document_text, blocks)`. `document_text` is every block's text
    joined by newlines; `Block.offset` is that block's start within it, and
    every offset a `Finding` reports indexes into it, so a reviewer can
    always confirm `document_text[f.evidence.start:f.evidence.end] ==
    f.evidence.quote`.

    Uses only `html.parser` from the standard library.
    """
    parser = _BlockExtractor()
    parser.feed(html_or_text)
    parser.close()
    parser.finish()
    return parser.text, parser.blocks


def document_text(html_or_text: str) -> str:
    """The plain text the detector searches. Finding offsets index into this."""
    return parse_blocks(html_or_text)[0]


def split_sentences(text: str) -> list[tuple[str, int]]:
    """Split `text` into `(sentence, offset_within_text)` pairs."""
    out: list[tuple[str, int]] = []
    pos = 0
    for sep in _SENTENCE_SPLIT_RE.finditer(text):
        piece = text[pos:sep.start()]
        if piece.strip():
            out.append((piece, pos))
        pos = sep.end()
    tail = text[pos:]
    if tail.strip():
        out.append((tail, pos))
    return out


# ---------------------------------------------------------------------------
# Subject-term matching (condition 2 — the false-positive killer)
# ---------------------------------------------------------------------------


def _singularise(word: str) -> str:
    """A deliberately minimal English plural fold, applied identically to
    the ledger side and the document side so the two agree.

    It is not a stemmer: "operating" does not become "operate", and
    "staffing" does not become "staff". Aggressive stemming is exactly how
    a matcher starts flagging the wrong sentences.
    """
    lowered = word.lower()
    if len(lowered) > 4 and lowered.endswith("ies"):
        return lowered[:-3] + "y"
    if len(lowered) > 4 and lowered.endswith(("ses", "xes", "zes", "ches", "shes")):
        return lowered[:-2]
    if len(lowered) > 3 and lowered.endswith("s") and not lowered.endswith("ss"):
        return lowered[:-1]
    return lowered


def _content_words(phrase: str) -> tuple[str, ...]:
    words = [_singularise(t) for t in _TOKEN_RE.findall(phrase)]
    return tuple(w for w in words if w and w not in STOPWORDS and len(w) > 1)


def subject_terms(fact: Fact) -> tuple[frozenset[str], tuple[frozenset[str], ...]]:
    """Derive a fact's matchable subject vocabulary from ledger data alone.

    Returns `(terms, phrases)`:

    * `terms` — every content word appearing in the fact's `subject` or any
      of its `subject_synonyms`, minus English function words. A single
      term in the sentence satisfies condition 2. Partial matching is
      required, not a nicety: the ledger's synonym is "countries served"
      while the document says "across 14 countries", and the synonym is
      "team members" while the document says "twelve hundred staff
      members". Demanding a whole phrase would miss both.
    * `phrases` — each subject/synonym as a set of its content words. When
      every word of one phrase is present, the match is a *full* subject
      match and scores higher confidence than a single-term match.

    Adding a synonym to `facts.yaml` extends both, with no code change.
    """
    phrases: list[frozenset[str]] = []
    terms: set[str] = set()
    for phrase in [fact.subject, *fact.subject_synonyms]:
        words = _content_words(phrase)
        if not words:
            continue
        phrases.append(frozenset(words))
        terms.update(words)
    return frozenset(terms), tuple(phrases)


def _subject_hits(
    sentence: str,
    terms: frozenset[str],
    phrases: tuple[frozenset[str], ...],
) -> tuple[list[tuple[int, int]], bool]:
    """Find subject-term occurrences in a sentence.

    Returns `(spans, full_phrase_match)`. Membership is order-free, which
    is what makes the rule word-order independent: the value may precede
    or follow the subject.
    """
    spans: list[tuple[int, int]] = []
    present: set[str] = set()
    for m in _TOKEN_RE.finditer(sentence):
        word = _singularise(m.group(0))
        present.add(word)
        if word in terms:
            spans.append((m.start(), m.end()))
    full = any(phrase <= present for phrase in phrases)
    return spans, full


# ---------------------------------------------------------------------------
# Value candidates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    quote: str
    start: int  # offset within the sentence
    end: int
    hedged: bool
    prior: PriorValue


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def _as_month_year(value: object) -> tuple[int, int] | None:
    """(year, month) if `value` is *entirely* one month-year form.

    Requires the match to span the whole string so that a ledger value like
    "renewed March 2023 by TUV" is not silently reduced to a bare date.
    """
    text = str(value).strip()
    matches = find_month_years(text)
    if len(matches) == 1 and matches[0].raw == text:
        return matches[0].year, matches[0].month
    return None


def _hedged_before(sentence: str, span_start: int) -> bool:
    window = sentence[max(0, span_start - _HEDGE_LOOKBACK_CHARS):span_start]
    return _HEDGE_BEFORE_RE.search(window) is not None


def _literal_occurrences(sentence: str, needle: str):
    pattern = r"(?<!\w)" + re.escape(needle.strip()).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.finditer(pattern, sentence, re.IGNORECASE)


def _numeric_candidates(sentence: str, fact: Fact) -> list[_Candidate]:
    current = _as_float(fact.value)
    out: list[_Candidate] = []
    for number in find_numbers(sentence):
        if current is not None and values_equivalent(number.value, current, fact.kind):
            continue  # a span stating the CURRENT value is never a finding
        for prior in fact.prior_values:
            prior_value = _as_float(prior.value)
            if prior_value is None:
                continue
            if values_equivalent(number.value, prior_value, fact.kind):
                out.append(
                    _Candidate(
                        quote=number.raw,
                        start=number.start,
                        end=number.end,
                        hedged=number.hedge is not None,
                        prior=prior,
                    )
                )
                break
    return out


def _text_candidates(sentence: str, fact: Fact) -> list[_Candidate]:
    """Candidates for `kind == "text"` facts.

    Two paths, because a text fact may or may not be a date:

    * month-year path — the ledger's value parses as a single month-year
      (e.g. "March 2023"), so any month-year in the sentence with the same
      month AND year matches, whatever its surface form ("03/2023",
      "Mar 2023", "March '23"). Vague periods ("early 2023", "Q1 2023")
      produce no month-year at all in `normalize`, and are deliberately
      left unmatched here rather than guessed at.
    * literal path — for text values that are not dates, the retired string
      itself, matched case-insensitively at word boundaries.
    """
    current_my = _as_month_year(fact.value)
    out: list[_Candidate] = []

    for month_year in find_month_years(sentence):
        stated = (month_year.year, month_year.month)
        if current_my is not None and stated == current_my:
            continue
        for prior in fact.prior_values:
            if _as_month_year(prior.value) == stated:
                out.append(
                    _Candidate(
                        quote=sentence[month_year.start:month_year.end],
                        start=month_year.start,
                        end=month_year.end,
                        hedged=_hedged_before(sentence, month_year.start),
                        prior=prior,
                    )
                )
                break

    taken = {(c.start, c.end) for c in out}
    for prior in fact.prior_values:
        if _as_month_year(prior.value) is not None:
            continue  # already covered by the month-year path
        for m in _literal_occurrences(sentence, str(prior.value)):
            if (m.start(), m.end()) in taken:
                continue
            out.append(
                _Candidate(
                    quote=m.group(0),
                    start=m.start(),
                    end=m.end(),
                    hedged=_hedged_before(sentence, m.start()),
                    prior=prior,
                )
            )
    out.sort(key=lambda c: (c.start, c.end))
    return out


# ---------------------------------------------------------------------------
# match_type and confidence
# ---------------------------------------------------------------------------


def _surface_key(text: str, fact: Fact) -> str:
    """Canonical surface form used to decide `exact` vs `paraphrase`.

    Two forms count as the same surface form when they differ only by
    digit grouping, case, or a trailing scale word that is spelled exactly
    like the leading word of the fact's own `unit`. Everything else — a
    spelled-out number, an abbreviation, a hedge, a reformatted date — is a
    paraphrase.

    Worked from the ledger's own data, so:

    * ledger prior `1200`, document "1,200"  -> both "1200"        -> exact
    * ledger prior `1200`, document "twelve hundred"               -> paraphrase
    * ledger prior `3.2` with unit "million people",
      document "3.2 million" -> trailing "million" is the unit head,
      dropped -> both "3.2"                                        -> exact
    * same fact, document "3.2m" -> "3.2m"                         -> paraphrase
    * ledger prior "March 2023", document "March 2023"             -> exact
    * ledger prior "March 2023", document "03/2023"                -> paraphrase
    * ledger prior `1200`, document "over 1,200" -> "over1200"     -> paraphrase
    """
    key = text.strip().lower()
    unit_head = (fact.unit or "").strip().lower().split(" ")[0] if fact.unit else ""
    if unit_head:
        key = re.sub(r"\s*\b" + re.escape(unit_head) + r"\b\s*$", "", key)
    return key.replace(",", "").replace(" ", "")


def _match_type(quote: str, prior: PriorValue, fact: Fact) -> str:
    if _surface_key(quote, fact) == _surface_key(str(prior.value), fact):
        return "exact"
    return "paraphrase"


def _confidence(
    match_type: str,
    hedged: bool,
    full_subject: bool,
    distance: int,
    sentence: str,
    current_in_sentence: bool,
    counted_noun_mismatch: bool,
) -> float:
    """Confidence in [floor, 1.0], from `CONFIDENCE_WEIGHTS`.

        confidence = base
                   - distance_penalty
                   - hedge_penalty
                   - partial_subject_penalty
                   - counted_noun_mismatch_penalty
                   - historical_marker_penalty
                   - negation_penalty
                   - current_value_in_sentence_penalty

    * **base** — 0.95 when the stated surface form is character-identical
      to the ledger's retired value (`exact`), 0.85 for a `paraphrase`.
      A paraphrase starts lower because reaching the value took an
      inference — a scale word, a spelled-out number, a reformatted date.
    * **distance** — 0.0005 per character between the value span and the
      nearest subject term, capped at 0.15. Adjacent ("1,200 permanent
      staff") costs nothing; opposite ends of a long sentence costs the
      cap. Nearness is corroboration, not proof, so the cap is small.
    * **hedge** — 0.10 when the value is hedged ("approximately 1,200"):
      the author was already signalling imprecision.
    * **partial subject** — 0.10 when only individual subject words were
      found rather than every word of one whole synonym phrase.
    * **counted noun mismatch** — 0.15 when the noun immediately after the
      number is neither a subject term nor part of the fact's unit, i.e.
      the figure is counting something else ("our staff distributed 1,200
      laptops"). See `_counted_noun_mismatch` for why this lowers the score
      rather than suppressing the finding.
    * **historical marker** — 0.45 when the sentence carries a phrase from
      `HISTORICAL_MARKERS` ("previously", "as of", "formerly"). Such a
      sentence may be legitimately describing the past, so it drops far
      down the list — but it is still SURFACED, never suppressed. Silently
      dropping a real stale claim because it sat next to the word
      "previously" is the failure mode this penalty exists to avoid.
    * **negation** — 0.25 for a negated sentence, same reasoning.
    * **current value also present** — 0.20 when the fact's current value
      appears in the same sentence, which usually means a deliberate
      then/now contrast ("grown from 1,200 to 1,450 staff").

    Every input is a structural property of the match. None of them
    inspects what the document is *about*.
    """
    w = CONFIDENCE_WEIGHTS
    score = w["base_exact"] if match_type == "exact" else w["base_paraphrase"]
    score -= min(
        w["max_distance_penalty"], distance * w["distance_penalty_per_char"]
    )
    if hedged:
        score -= w["hedge_penalty"]
    if not full_subject:
        score -= w["partial_subject_penalty"]
    if counted_noun_mismatch:
        score -= w["counted_noun_mismatch_penalty"]
    if _HISTORICAL_RE.search(sentence):
        score -= w["historical_marker_penalty"]
    if _NEGATION_RE.search(sentence):
        score -= w["negation_penalty"]
    if current_in_sentence:
        score -= w["current_value_in_sentence_penalty"]
    return round(max(w["floor"], min(1.0, score)), 3)


def finding_id(doc_id: str, fact_id: str, start: int, end: int) -> str:
    """Deterministic finding id: a stable hash of (doc_id, fact_id, start, end).

    Re-running the audit over unchanged input reproduces every id exactly,
    so a reviewer's accept/reject decisions survive a re-run. Nothing
    volatile (time, iteration order, object identity) enters the hash.
    """
    payload = f"{doc_id}\x1f{fact_id}\x1f{start}\x1f{end}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _counted_noun_mismatch(
    sentence: str, cand: _Candidate, terms: frozenset[str], fact: Fact
) -> bool:
    """True when the number is plainly counting something other than the fact.

    In English a count is followed by the noun it counts: "1,200 permanent
    staff", "14 countries", "3.2m people". So when the very next content
    word after the value is neither a subject term nor a word from the
    fact's own `unit`, the number is most likely counting something else —
    "our staff distributed 1,200 laptops" counts laptops, not staff.

    This is a confidence penalty and deliberately NOT a suppression: plenty
    of legitimate claims put nothing countable after the figure
    ("permanent staff worldwide: 1,200 at last count", "1,200 is the number
    of employees"), and suppressing those would trade a false positive for
    a miss. It also does not apply to `kind == "text"` facts — a date does
    not count a noun.
    """
    if fact.kind == "text":
        return False
    match = _TOKEN_RE.search(sentence, cand.end)
    if match is None:
        return False
    word = _singularise(match.group(0))
    if len(word) <= 1 or word in STOPWORDS or word in terms:
        return False
    return word not in _content_words(fact.unit or "")


def _nearest_distance(cand: _Candidate, hits: list[tuple[int, int]]) -> int:
    """Character gap between the value span and the closest subject term.

    Zero when they overlap or touch. Word order is irrelevant here by
    construction: the gap is measured the same way whether the subject
    comes before or after the value.
    """
    best = None
    for hit_start, hit_end in hits:
        if hit_start < cand.end and cand.start < hit_end:
            gap = 0
        elif hit_end <= cand.start:
            gap = cand.start - hit_end
        else:
            gap = hit_start - cand.end
        if best is None or gap < best:
            best = gap
    return best or 0


def _current_value_in_sentence(sentence: str, fact: Fact) -> bool:
    current_number = _as_float(fact.value)
    if current_number is not None and fact.kind != "text":
        return any(
            values_equivalent(n.value, current_number, fact.kind)
            for n in find_numbers(sentence)
        )
    current_my = _as_month_year(fact.value)
    if current_my is not None:
        return any(
            (my.year, my.month) == current_my for my in find_month_years(sentence)
        )
    return bool(next(_literal_occurrences(sentence, str(fact.value)), None))


def _detect_in_blocks(
    doc_text: str, blocks: list[Block], doc_id: str, fact: Fact
) -> list[Finding]:
    if not fact.prior_values:
        return []

    terms, phrases = subject_terms(fact)
    if not terms:
        return []

    findings: list[Finding] = []
    for block in blocks:
        for sentence, sentence_offset in split_sentences(block.text):
            hits, full_subject = _subject_hits(sentence, terms, phrases)
            if not hits:
                # Condition 2 failed: no subject synonym in this sentence.
                # Whatever numbers it contains are somebody else's numbers.
                continue

            if fact.kind == "text":
                candidates = _text_candidates(sentence, fact)
            else:
                candidates = _numeric_candidates(sentence, fact)
            if not candidates:
                continue

            current_here = _current_value_in_sentence(sentence, fact)

            for cand in candidates:
                distance = _nearest_distance(cand, hits)
                match_type = _match_type(cand.quote, cand.prior, fact)
                start = block.offset + sentence_offset + cand.start
                end = block.offset + sentence_offset + cand.end
                findings.append(
                    Finding(
                        id=finding_id(doc_id, fact.id, start, end),
                        fact_id=fact.id,
                        doc_id=doc_id,
                        match_type=match_type,
                        stated_value=cand.quote,
                        canonical_value=str(fact.value),
                        source=fact.source,
                        as_of=fact.as_of,
                        confidence=_confidence(
                            match_type=match_type,
                            hedged=cand.hedged,
                            full_subject=full_subject,
                            distance=distance,
                            sentence=sentence,
                            current_in_sentence=current_here,
                            counted_noun_mismatch=_counted_noun_mismatch(
                                sentence, cand, terms, fact
                            ),
                        ),
                        evidence=Evidence(
                            sentence=sentence.strip(),
                            quote=cand.quote,
                            start=start,
                            end=end,
                            chunk_id=block.chunk_id,
                            element_index=block.element_index,
                        ),
                        matched_prior=cand.prior,
                    )
                )
    return findings


def detect(html_or_text: str, doc_id: str, fact: Fact) -> list[Finding]:
    """Find every stale statement of ONE fact in one document.

    Returns findings in document order. Empty list when the document makes
    no retired claim about this fact — which includes the case where it
    states the fact correctly, and the case where a retired *number*
    appears with nothing to tie it to this subject.
    """
    doc_text, blocks = parse_blocks(html_or_text)
    findings = _detect_in_blocks(doc_text, blocks, doc_id, fact)
    findings.sort(key=lambda f: (f.evidence.start, f.evidence.end, f.fact_id))
    return findings


def detect_all(html_or_text: str, doc_id: str, ledger: FactLedger) -> list[Finding]:
    """Find every stale statement of ANY ledger fact in one document.

    Parses the document once and runs every fact over it. Ordering is
    document order, then fact id, so the output is stable across runs and
    independent of ledger iteration order.
    """
    doc_text, blocks = parse_blocks(html_or_text)
    findings: list[Finding] = []
    for fact in ledger:
        findings.extend(_detect_in_blocks(doc_text, blocks, doc_id, fact))
    findings.sort(key=lambda f: (f.evidence.start, f.evidence.end, f.fact_id))
    return findings
