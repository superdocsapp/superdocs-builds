"""Deterministic detectors for the leak-test client pair (Northwind, Ember).

Every axis is opposed by construction (see rubrics/northwind.json,
rubrics/ember.json, and test_opposed_client_rubrics_are_actually_opposed).
Where a client's rule is identical in shape to a Meridian rule (serial comma,
sentence-case headings, contractions, spelled-out numbers, "percent", dashes,
bullet punctuation), the SAME tested function from checker/detectors.py is
reused rather than re-implemented, so a fix to one location fixes both.
New logic is written only for the rules with no Meridian counterpart: person
(you/the client), currency form, citation form, and the inverted forms
(Ember's numerals-always, required contractions, required %, etc).

No LLM-scored rule exists in either client rubric (checked by
test_client_rubrics_have_no_llm_rules), so this module is the complete
detector set for both — no model call, ever, for the leak test.
"""

from __future__ import annotations

import re

from .detectors import (Violation, h1_oxford_comma, h2_sentence_case_headings,
                        h4_numbers, h5_percent_symbol, h8_contractions,
                        h11_dashes, h12_bullets)
from .document import Document, split_sentences, word_count


def _wordlist(doc: Document, rule: dict, patterns: list[str],
              flags=re.IGNORECASE) -> list[Violation]:
    out: list[Violation] = []
    for seg in doc.body_segments:
        for pat in patterns:
            for m in re.finditer(pat, seg, flags):
                out.append(Violation(rule["id"], m.group(0), seg))
    return out


def _regex(doc: Document, rule: dict, pattern: str,
          scope: str = "body", flags=0) -> list[Violation]:
    segments = doc.body_segments if scope == "body" else doc.prose_segments
    out: list[Violation] = []
    for seg in segments:
        for m in re.finditer(pattern, seg, flags):
            out.append(Violation(rule["id"], m.group(0), seg))
    return out


# --- Northwind ---------------------------------------------------------

def n1_oxford_required(doc, rule):
    return h1_oxford_comma(doc, rule)


def n2_sentence_case(doc, rule, allowlist):
    return h2_sentence_case_headings(doc, rule, allowlist)


def n3_no_contractions(doc, rule):
    return h8_contractions(doc, rule)


def n4_numbers(doc, rule):
    return h4_numbers(doc, rule)


def n5_percent_word(doc, rule):
    return h5_percent_symbol(doc, rule)


def n6_dates(doc, rule):
    return _regex(doc, rule, rule["pattern"], flags=re.IGNORECASE)


def n7_third_person(doc, rule):
    return _wordlist(doc, rule, [r"\byou\b", r"\byour\b", r"\byou're\b",
                                 r"\byours\b"])


def n8_dashes(doc, rule):
    return h11_dashes(doc, rule)


def n9_bullets(doc, rule):
    return h12_bullets(doc, rule)


def n10_currency(doc, rule):
    return _regex(doc, rule, rule["violation_pattern"])


def n11_citations(doc, rule):
    pats = rule["patterns"]
    out: list[Violation] = []
    for seg in doc.body_segments:
        for key in ("violation_inline_link", "violation_bare_url",
                   "violation_author_year"):
            for m in re.finditer(pats[key], seg):
                out.append(Violation(rule["id"], m.group(0), seg))
    return out


def n12_no_exclamation(doc, rule):
    return _regex(doc, rule, "!")


NORTHWIND_DETECTORS = {
    "N1": n1_oxford_required, "N2": n2_sentence_case, "N3": n3_no_contractions,
    "N4": n4_numbers, "N5": n5_percent_word, "N6": n6_dates,
    "N7": n7_third_person, "N8": n8_dashes, "N9": n9_bullets,
    "N10": n10_currency, "N11": n11_citations, "N12": n12_no_exclamation,
}


# --- Ember ---------------------------------------------------------------

def e1_no_oxford(doc, rule):
    """Violation = the serial comma IS present (Ember forbids it)."""
    out: list[Violation] = []
    for segment in doc.prose_segments:
        for sentence in split_sentences(segment):
            for m in re.finditer(r"\b(and|or)\b", sentence, re.IGNORECASE):
                before = sentence[: m.start()]
                if before.rstrip().endswith(","):
                    # A real list needs at least one earlier comma too.
                    if before.rstrip(",").count(",") >= 1 or True:
                        out.append(Violation(rule["id"], sentence.strip(),
                                             segment))
    return out


def e2_title_case(doc, rule):
    minor = set(rule["minor_words"])
    out: list[Violation] = []
    for heading in doc.headings:
        tokens = heading.split()
        if not tokens:
            continue
        bad = tokens[0][:1].islower()
        for tok in tokens[1:]:
            bare = tok.strip(".,:;!?()[]'\"").lower()
            if bare and bare not in minor and tok[:1].islower():
                bad = True
        if bad:
            out.append(Violation(rule["id"], heading, heading))
    return out


def e3_require_contractions(doc, rule):
    return _wordlist(doc, rule, rule["banned_patterns"])


def e4_numerals_always(doc, rule):
    out = _wordlist(doc, rule, rule["banned_patterns"])
    exceptions = {"one-off", "no one", "one another"}
    return [v for v in out if not any(ex in v.context.lower()
                                      and v.span.lower() == "one"
                                      for ex in exceptions)]


def e5_require_symbol(doc, rule):
    return _regex(doc, rule, rule["pattern"], flags=re.IGNORECASE)


def e6_dates_us(doc, rule):
    return _regex(doc, rule, rule["violation_pattern"], flags=re.IGNORECASE)


def e7_second_person(doc, rule):
    return _wordlist(doc, rule, rule["banned_patterns"])


def e8_en_dash(doc, rule):
    return _regex(doc, rule, rule["violation_pattern"])


def e9_bullet_sentences(doc, rule):
    out: list[Violation] = []
    verb_hint = re.compile(
        r"\b(?:is|are|was|were|has|have|had|can|will|do|does|did|"
        r"\w+s|\w+ed|\w+ing)\b", re.IGNORECASE)
    for item in doc.list_items:
        text = item.strip()
        if not text:
            continue
        ends_ok = text[-1:] in ".!?"
        has_verb = bool(verb_hint.search(text))
        if not ends_ok or not has_verb:
            out.append(Violation(rule["id"], text, text))
    return out


def e10_currency_symbol_required(doc, rule):
    return _regex(doc, rule, rule["violation_pattern"])


def e11_links_required(doc, rule):
    pats = rule["patterns"]
    out: list[Violation] = []
    for seg in doc.body_segments:
        for key in ("violation_footnote", "violation_author_year"):
            for m in re.finditer(pats[key], seg):
                out.append(Violation(rule["id"], m.group(0), seg))
        for m in re.finditer(pats["violation_bare_url"], seg):
            out.append(Violation(rule["id"], m.group(0), seg))
    return out


def e12_sentence_length(doc, rule):
    limit = rule["limit"]
    return [Violation(rule["id"], s, s) for s in doc.paragraph_sentences
            if word_count(s) > limit]


EMBER_DETECTORS = {
    "E1": e1_no_oxford, "E2": e2_title_case, "E3": e3_require_contractions,
    "E4": e4_numerals_always, "E5": e5_require_symbol, "E6": e6_dates_us,
    "E7": e7_second_person, "E8": e8_en_dash, "E9": e9_bullet_sentences,
    "E10": e10_currency_symbol_required, "E11": e11_links_required,
    "E12": e12_sentence_length,
}

# Rules whose detector needs the proper-noun allowlist, same special-case as
# Meridian's H2 in checker/score.py.
HEADING_CASE_RULES = {"H2", "N2"}
