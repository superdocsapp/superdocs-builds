"""Citations: tying each exhibit to the sentence in the brief that relies on it.

``plan_citations`` reads the brief, finds the sentence each exhibit is most
relevant to (by keyword overlap with the exhibit's title and what it proves),
and proposes a citation at that anchor. ``apply_citations`` splices accepted
citations back into the brief text.

Because citations are *computed from the set*, any late insertion (which
renumbers the set) automatically renumbers every in-brief citation too.
"""

from __future__ import annotations

import re

from .model import Citation, ExhibitSet

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "his",
    "her", "are", "was", "were", "will", "would", "should", "shall", "not",
    "but", "they", "their", "them", "into", "upon", "because", "according",
    "however", "therefore", "furthermore", "moreover", "thereby", "please",
    "respectfully", "applicant", "respondent", "brief", "exhibit", "evidence",
    "document", "case", "court", "section", "submitted", "attached", "hereby",
    "also", "then", "each", "such", "may", "application", "support",
    "supporting", "petition", "granted", "granting", "approved", "approval",
    "request", "requests", "requested", "foregoing", "foregone", "reason",
    "reasons", "presented", "stated", "statement", "states", "state", "united",
    "accordingly", "application",
}


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z]{4,}", text.lower())
    out: set[str] = set()
    for w in words:
        if w in _STOP:
            continue
        stem = _stem(w)
        if stem in _STOP:  # catch inflections of stopwords (support/supports/...)
            continue
        out.add(stem)
    return out


def _topic_keywords(title: str) -> set[str]:
    """The exhibit's topic: stemmed words from its filename title, minus
    generic framing words and plural/possessive noise."""
    out: set[str] = set()
    for w in re.findall(r"[A-Za-z]{4,}", title.lower()):
        if w in _STOP:
            continue
        stem = _stem(w)
        if stem in _STOP or stem in _TITLE_NOISE:
            continue
        out.add(stem)
    return out


# Framing words shared across many exhibit titles that carry no topic signal
# ("Joint Bank Statements" / "Joint Lease" / "Joint Tax Return"). Words like
# "marriage", "wedding" or "letters" ARE the topic and are kept.
_TITLE_NOISE = {
    "joint", "statement", "statements", "record", "records",
}


def _stem(word: str) -> str:
    """Light prefix-stemming so inflected forms match: travel/travelled,
    photo/photographs, account/accounts."""
    return word[:5] if len(word) > 5 else word


def _sentences(brief: str) -> list[tuple[int, int, str]]:
    """Split the brief into substantive sentences, returning (start, end, text).

    Headings (``#``) and fragments shorter than 20 characters are skipped — a
    citation anchored at a heading would be useless.
    """
    spans = []
    for m in re.finditer(r"[^.!?\n]+[.!?]?\s*", brief):
        text = m.group().strip()
        if not text or text.startswith("#") or len(text) < 20:
            continue
        spans.append((m.start(), m.end(), text))
    return spans


def plan_citations(set_: ExhibitSet, brief: str) -> list[Citation]:
    """Propose one citation per exhibit, anchored at the brief sentence that
    most relies on what that exhibit proves.

    Anchors are assigned greedily so no two citations crowd one sentence
    unnecessarily: a sentence hosts at most ``MAX_CITES_PER_SENTENCE`` citations
    (two exhibits can genuinely rely on the same sentence, e.g. "...joint bank
    accounts and a joint tax return..."), and each exhibit takes its best
    available sentence (highest keyword overlap, then earliest position). An
    exhibit with no topical match takes the earliest uncited sentence; when no
    sentence has room it falls back to the very end of the brief (empty anchor).
    """
    sentences = _sentences(brief)
    if not sentences:
        return []
    # Rank each exhibit's candidate sentences, then assign greedily in order of
    # match strength — an exhibit with a strong topical sentence claims it first,
    # so a weak/no-match exhibit can never steal a sentence a real match needs.
    # Scoring is weighted: filename-title keywords (the exhibit's topic) count 10x
    # a body-text keyword, so accidental body-text overlaps ("supports" vs
    # "supported") never outrank a real topical match.
    entries: list[tuple[Exhibit, int, list[tuple[int, int, int, int, str]]]] = []
    for ex in set_:
        title_kw = _topic_keywords(ex.title)
        content_kw = _evidence_content_keywords(ex.content)
        scored = []
        for start, end, sent in sentences:
            score, offset = _score_sentence(title_kw, content_kw, start, sent)
            scored.append((score, offset, start, end, sent))
        scored.sort(key=lambda t: (-t[0], t[1]))
        best = scored[0][0] if scored else 0
        entries.append((ex, best, scored))
    entries.sort(key=lambda e: -e[1])

    uses: dict[tuple[int, int], int] = {}
    plans: list[Citation] = []
    for ex, _best, scored in entries:
        chosen = next(
            ((s, off, st, en, txt) for s, off, st, en, txt in scored
             if uses.get((st, en), 0) < MAX_CITES_PER_SENTENCE),
            None,
        )
        if chosen is None:
            anchor = ""
            rationale = (
                f"Every sentence already cites another exhibit; appended at the "
                f"end of the brief for completeness."
            )
        else:
            score, _off, start, end, sent = chosen
            uses[(start, end)] = uses.get((start, end), 0) + 1
            anchor = sent[:80].strip()
            if score > 0:
                rationale = f"Relies on what Exhibit {ex.number} proves ({ex.proves[:80]})."
            else:
                rationale = "No direct topical match; placed at an uncited sentence for completeness."
        plans.append(Citation(
            sentence=f"See Exhibit {ex.number} ({ex.title}), which evidences {ex.proves.rstrip('.').rstrip()}.",
            anchor=anchor,
            exhibit_number=ex.number,
            rationale=rationale,
        ))
    return plans


def apply_citations(brief: str, citations: list[Citation]) -> str:
    """Insert an in-text citation after each accepted citation's anchor
    sentence. Markers on the same anchor cluster together ("... [See Exhibit 4]
    [See Exhibit 5]"). Idempotent per exhibit: a marker for that exhibit already
    beside its anchor is not re-inserted, so re-running never duplicates."""
    result = brief
    for cit in citations:
        marker = f" [See Exhibit {cit.exhibit_number}]"
        if not cit.anchor:
            if f"[See Exhibit {cit.exhibit_number}]" not in result:
                result = f"{result.rstrip()}\n{marker.strip()}\n"
            continue
        idx = result.find(cit.anchor)
        if idx == -1:
            # the anchor sentence no longer exists verbatim (already edited):
            # append the citation at the end rather than silently dropping it
            if f"[See Exhibit {cit.exhibit_number}]" not in result:
                result = f"{result.rstrip()}\n{marker.strip()}\n"
            continue
        end = idx + len(cit.anchor)
        if re.search(r"\[See Exhibit %d\]" % cit.exhibit_number, result[end:end + 80]):
            continue  # this exhibit already cites this anchor
        tail = result[end:]
        cluster = re.match(r"(?: \[See Exhibit \d+\])*", tail)
        insert_at = end + cluster.end()
        result = result[:insert_at] + marker + result[insert_at:]
    return result


def _earliest_keyword_offset(ex_kw: set[str], sent: str) -> int:
    """Character offset within ``sent`` of its first keyword that is in ``ex_kw``
    (stemmed match). Returns a large sentinel when none overlaps."""
    low = sent.lower()
    for m in re.finditer(r"[A-Za-z]{4,}", low):
        if _stem(m.group()) in ex_kw:
            return m.start()
    return 10**9


def _evidence_content_keywords(text: str) -> set[str]:
    """Content keywords, excluding proper nouns (capitalised words) and
    stopwords — names and places must never drive matching."""
    out: set[str] = set()
    for tok in re.findall(r"[A-Za-z]{4,}", text):
        if tok[0].isupper():
            continue
        word = tok.lower()
        if word in _STOP:
            continue
        stem = _stem(word)
        if stem in _STOP:
            continue
        out.add(stem)
    return out


# A keyword shared with the exhibit's filename/title is a strong, reliable signal
# (the topic); a keyword from the body text is weak (the body may merely mention
# the word). Title weight is high enough that one genuine topic match beats any
# pile of generic body-text overlap ("couple, travel, wedding, family") so an
# exhibit cites the sentence about *it*, not the sentence that merely resembles
# it. Content weight still matters for exhibits with no topic match at all.
TITLE_WEIGHT = 10
CONTENT_WEIGHT = 1
# Two exhibits may legitimately rely on the same sentence ("...joint bank
# accounts and a joint tax return filed..."); a sentence hosts at most this many
# citations before later exhibits look elsewhere.
MAX_CITES_PER_SENTENCE = 2


def _score_sentence(title_kw: set[str], content_kw: set[str],
                    start: int, sent: str) -> tuple[int, int]:
    """Weighted (score, absolute_offset) of one sentence for one exhibit.

    ``score`` favours title-topic matches; ``offset`` is the position of the
    first matching keyword, used to break ties (earlier = the brief relies on it
    sooner). A sentence with no overlap scores (0, 10**9).
    """
    sent_kw = _keywords(sent)
    score = TITLE_WEIGHT * len(title_kw & sent_kw) + CONTENT_WEIGHT * len(content_kw & sent_kw)
    if not score:
        return 0, 10**9
    return score, start + _earliest_keyword_offset(title_kw | content_kw, sent)
