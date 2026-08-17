"""Deterministic detectors for the Meridian house rubric (H1-H14 except H3).

Every function here is a pure function of (Document, rubric_rule) and returns a
list of Violation. No model calls, no network, no randomness: the same document
scores identically on every run, in both arms, forever.

Where the rubric names a `guard` or a `false_positive_notes`, the guard is
implemented here and the false-positive shape is pinned by a fixture test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .document import Document, split_sentences, word_count


@dataclass(frozen=True)
class Violation:
    rule_id: str
    span: str
    context: str = ""


# Sentence-initial adverbial markers. A comma following one of these within the
# first few tokens is an adverbial comma, not a list comma (rubric H1 guard).
_ADVERBIAL_LEAD = {
    "in", "on", "at", "by", "after", "before", "since", "although", "though",
    "however", "first", "second", "finally", "during", "while", "if", "when",
    "for", "with", "under", "despite", "following", "given", "as", "meanwhile",
    "overall", "typically", "historically", "notably", "accordingly",
}

_NUMBER_WORDS_SMALL = ["zero", "one", "two", "three", "four", "five", "six",
                       "seven", "eight", "nine"]
_NUMBER_WORDS_LARGE = ["ten", "eleven", "twelve", "thirteen", "fourteen",
                       "fifteen", "sixteen", "seventeen", "eighteen",
                       "nineteen", "twenty", "thirty", "forty", "fifty",
                       "sixty", "seventy", "eighty", "ninety", "hundred",
                       "thousand"]

# Tokens that make `'s` a contraction rather than a possessive (H8 guard).
_CONTRACTION_S_HOSTS = {"it", "that", "there", "he", "she", "what", "who",
                        "here", "this", "where", "let", "how"}


def _iter_conjunctions(sentence: str):
    for m in re.finditer(r"\b(and|or)\b", sentence, re.IGNORECASE):
        yield m


def h1_oxford_comma(doc: Document, rule: dict) -> list[Violation]:
    """Lists of three or more must carry the serial comma.

    Guard: a comma that follows a sentence-initial adverbial phrase is not a
    list comma. Pinned by tests/fixtures/false_positive_guards.md.
    """
    out: list[Violation] = []
    for segment in doc.prose_segments:
        for sentence in split_sentences(segment):
            tokens = sentence.split()
            lead = tokens[0].lower().strip(",.;:") if tokens else ""
            for m in _iter_conjunctions(sentence):
                before = sentence[: m.start()]
                commas = [c.start() for c in re.finditer(r",", before)]
                if not commas:
                    continue
                # Adverbial-lead guard: the only comma before the conjunction
                # closes a sentence-initial adverbial phrase.
                if lead in _ADVERBIAL_LEAD:
                    lead_comma = commas[0]
                    words_before_comma = word_count(sentence[:lead_comma])
                    if len(commas) == 1 and words_before_comma <= 4:
                        continue
                # Serial comma present if the text immediately before the
                # conjunction ends with a comma.
                if before.rstrip().endswith(","):
                    continue
                out.append(Violation(rule["id"], sentence.strip(), segment))
    return out


def h2_sentence_case_headings(doc: Document, rule: dict,
                              allowlist: set[str]) -> list[Violation]:
    out: list[Violation] = []
    for heading in doc.headings:
        tokens = heading.split()
        for token in tokens[1:]:
            bare = token.strip(".,:;!?()[]'\"")
            if not bare or not bare[0].isupper():
                continue
            if bare in allowlist:
                continue
            if re.fullmatch(r"[A-Z]{2,5}", bare):  # acronym
                continue
            out.append(Violation(rule["id"], heading, heading))
            break
    return out


_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|"
           "Oct|Nov|Dec")


def _mask_for_numbers(text: str) -> str:
    """Blank out spans H4 must not see: years, versions, currency, dates.

    Date day-numbers are masked because they are date components, not prose
    numbers: H6 governs date formatting, and nobody writes "January one".
    Added after real model prose produced "between January 1 and March 31" and
    H4 flagged the bare 1. Pinned by tests/fixtures/h4_date_daynumber.md.
    """
    text = re.sub(r"\bv?\d+(?:\.\d+)+\b", " ", text)          # version strings
    text = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)            # years
    text = re.sub(rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}\b", " ", text,
                  flags=re.IGNORECASE)                         # "March 31"
    text = re.sub(rf"\b\d{{1,2}}\s+(?:{_MONTHS})\b", " ", text,
                  flags=re.IGNORECASE)                         # "13 August"
    text = re.sub(r"[$£€]\s?\d[\d,]*(?:\.\d+)?", " ", text)    # $ currency
    text = re.sub(r"\b(?:USD|GBP|EUR)\s?\d[\d,]*(?:\.\d+)?", " ", text)
    return text


def h4_numbers(doc: Document, rule: dict) -> list[Violation]:
    out: list[Violation] = []
    units = "|".join(re.escape(u) for u in rule["unit_tokens"])
    for segment in doc.prose_segments:
        masked = _mask_for_numbers(segment)
        # (a) bare single digit not attached to a unit
        for m in re.finditer(r"(?<![\d.,%$£€-])\b(\d)\b(?![\d.,%-])", masked):
            tail = masked[m.end():].lstrip()
            # The unit may be separated from the numeral by a modifier or two:
            # "5 business days" is numerals-with-units, not a spell-out miss.
            # Window of three tokens; found against real model prose.
            if re.match(rf"^(?:\w+\s+){{0,2}}(?:{units})\b", tail):
                continue
            # Span carries the following word ("3 critical", not "3"): a bare
            # digit is not locatable in a document containing other digits,
            # and spans are both quoted into corrections and used by the
            # normalizer to target a replacement.
            next_word = re.match(r"^([A-Za-z][\w-]*)", tail)
            span = f"{m.group(0)} {next_word.group(1)}" if next_word else m.group(0)
            out.append(Violation(rule["id"], span, segment))
        # (b) number word for ten or above
        for m in re.finditer(rf"\b({'|'.join(_NUMBER_WORDS_LARGE)})\b",
                             masked, re.IGNORECASE):
            out.append(Violation(rule["id"], m.group(0), segment))
        # (c) small number word attached to a unit
        for m in re.finditer(
                rf"\b({'|'.join(_NUMBER_WORDS_SMALL)})\s+({units})\b",
                masked, re.IGNORECASE):
            out.append(Violation(rule["id"], m.group(0), segment))
    return out


def h5_percent_symbol(doc: Document, rule: dict) -> list[Violation]:
    return [Violation(rule["id"], m.group(0), seg)
            for seg in doc.prose_segments
            for m in re.finditer(rule["pattern"], seg)]


def h6_dates(doc: Document, rule: dict) -> list[Violation]:
    return [Violation(rule["id"], m.group(0), seg)
            for seg in doc.body_segments
            for m in re.finditer(rule["pattern"], seg, re.IGNORECASE)]


def h7_citations(doc: Document, rule: dict) -> list[Violation]:
    pats = rule["patterns"]
    out: list[Violation] = []
    for seg in doc.body_segments:
        for m in re.finditer(pats["bare_url"], seg):
            out.append(Violation(rule["id"], m.group(0), seg))
        wellformed = {m.group(0) for m in
                      re.finditer(pats["wellformed_citation"], seg)}
        for m in re.finditer(pats["citation_like"], seg):
            if m.group(0) not in wellformed:
                out.append(Violation(rule["id"], m.group(0), seg))
    return out


def h8_contractions(doc: Document, rule: dict) -> list[Violation]:
    """Contractions banned. Possessive `'s` is not a contraction (H8 guard)."""
    out: list[Violation] = []
    for seg in doc.body_segments:
        for m in re.finditer(r"\b(\w+)['’](s|t|re|ve|ll|d|m)\b", seg,
                             re.IGNORECASE):
            host, suffix = m.group(1).lower(), m.group(2).lower()
            if suffix == "s" and host not in _CONTRACTION_S_HOSTS:
                continue  # possessive
            out.append(Violation(rule["id"], m.group(0), seg))
    return out


def h9_sentence_length(doc: Document, rule: dict) -> list[Violation]:
    limit = rule["limit"]
    return [Violation(rule["id"], s, s)
            for s in doc.paragraph_sentences if word_count(s) > limit]


def h10_hype_words(doc: Document, rule: dict) -> list[Violation]:
    pattern = r"\b(?:" + "|".join(re.escape(w) for w in rule["wordlist"]) + r")\b"
    return [Violation(rule["id"], m.group(0), seg)
            for seg in doc.body_segments
            for m in re.finditer(pattern, seg, re.IGNORECASE)]


def h11_dashes(doc: Document, rule: dict) -> list[Violation]:
    out: list[Violation] = []
    for seg in doc.body_segments:
        for m in re.finditer(r"(?:\s-{1,2}\s|\s–\s|\s—\s)", seg):
            # numeric range guard: 10 - 20
            before = seg[max(0, m.start() - 6):m.start()]
            after = seg[m.end():m.end() + 6]
            if re.search(r"\d\s*$", before) and re.match(r"^\s*\d", after):
                continue
            out.append(Violation(rule["id"], m.group(0).strip() or "-", seg))
    return out


def h12_bullets(doc: Document, rule: dict) -> list[Violation]:
    out: list[Violation] = []
    for item in doc.list_items:
        text = item.strip()
        if not text:
            continue
        first_alpha = next((c for c in text if c.isalpha()), "")
        bad_case = bool(first_alpha) and first_alpha.islower()
        bad_end = text[-1] in ".!?;:"
        if bad_case or bad_end:
            out.append(Violation(rule["id"], text, text))
    return out


def h13_acronyms(doc: Document, rule: dict) -> list[Violation]:
    never = set(rule["never_expand"])
    text = doc.body_text
    seen: set[str] = set()
    out: list[Violation] = []
    for m in re.finditer(r"\b([A-Z]{2,5})\b", text):
        acr = m.group(1)
        if acr in never or acr in seen:
            continue
        seen.add(acr)
        window = text[max(0, m.start() - 90):m.start()]
        expanded = re.search(r"(?:[A-Z][A-Za-z]+\s+){1,4}\($", window)
        if expanded:
            continue
        out.append(Violation(rule["id"], acr, text[max(0, m.start() - 40):m.end() + 10]))
    return out


def h14_person(doc: Document, rule: dict) -> list[Violation]:
    out: list[Violation] = []
    for seg in doc.body_segments:
        for entry in rule["banned_patterns"]:
            # Entries carry their own case sensitivity: 'the reader' and
            # 'one should' must match at the start of a sentence too, while
            # \bI\b must not match a lowercase 'i'.
            pattern = entry["pattern"] if isinstance(entry, dict) else entry
            flags = re.IGNORECASE if (isinstance(entry, dict)
                                      and entry.get("ignore_case")) else 0
            for m in re.finditer(pattern, seg, flags):
                out.append(Violation(rule["id"], m.group(0), seg))
    return out


DETERMINISTIC_DETECTORS = {
    "H1": h1_oxford_comma,
    "H2": h2_sentence_case_headings,
    "H4": h4_numbers,
    "H5": h5_percent_symbol,
    "H6": h6_dates,
    "H7": h7_citations,
    "H8": h8_contractions,
    "H9": h9_sentence_length,
    "H10": h10_hype_words,
    "H11": h11_dashes,
    "H12": h12_bullets,
    "H13": h13_acronyms,
    "H14": h14_person,
}
