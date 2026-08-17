"""Deterministic normalizer: repairs a seed draft to zero deterministic violations.

Runs between the prose stage and the injector. No model call, no network.

Contract: `normalize()` either returns a document that the committed checker
scores at zero on all 13 deterministic rules, or it raises. It never returns a
partially repaired document, because a document whose residual violation count
is unknown makes its difficulty unknown, and uniform difficulty is the whole
point of the profile.

H3 (passive voice) is not repaired — a deterministic passive-to-active rewrite
is not possible. Residual H3 is measured and handed to the injector, which
injects the difference. A draft whose base H3 already exceeds the H3 target is
rejected for regeneration.
"""

from __future__ import annotations

import re
from pathlib import Path

from checker.detectors import DETERMINISTIC_DETECTORS, Violation
from checker.document import Document, split_sentences, word_count
from checker.h3 import MockH3Provider
from checker.score import load_rubric, score_document

MAX_PASSES = 40


class NormalizationError(RuntimeError):
    """Raised when a draft cannot be repaired to zero deterministic violations."""


_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
_MONTH_BY_NUM = {v: k for k, v in _MONTHS.items()}
_MONTH_ABBR = {"Jan": "January", "Feb": "February", "Mar": "March",
               "Apr": "April", "Jun": "June", "Jul": "July", "Aug": "August",
               "Sep": "September", "Sept": "September", "Oct": "October",
               "Nov": "November", "Dec": "December", "May": "May"}

_NUM_WORD = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
             6: "six", 7: "seven", 8: "eight", 9: "nine"}
_WORD_NUM = {w: n for n, w in _NUM_WORD.items()}
_WORD_NUM.update({"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
                  "fourteen": 14, "fifteen": 15, "sixteen": 16,
                  "seventeen": 17, "eighteen": 18, "nineteen": 19,
                  "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
                  "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
                  "hundred": 100, "thousand": 1000})

_CONTRACTIONS = {
    "it's": "it is", "that's": "that is", "there's": "there is",
    "he's": "he is", "she's": "she is", "what's": "what is",
    "who's": "who is", "here's": "here is", "let's": "let us",
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "won't": "will not", "can't": "cannot", "isn't": "is not",
    "aren't": "are not", "wasn't": "was not", "weren't": "were not",
    "hasn't": "has not", "haven't": "have not", "hadn't": "had not",
    "shouldn't": "should not", "wouldn't": "would not",
    "couldn't": "could not", "we're": "we are", "they're": "they are",
    "you're": "you are", "we've": "we have", "they've": "they have",
    "you've": "you have", "we'll": "we will", "they'll": "they will",
    "you'll": "you will", "i'm": "I am", "i've": "I have",
}

_HYPE = {
    "leverage": "use", "leveraging": "using", "utilize": "use",
    "utilizing": "using", "robust": "reliable", "seamless": "smooth",
    "seamlessly": "smoothly", "best-in-class": "strong", "synergy": "overlap",
    "synergies": "overlaps", "cutting-edge": "current",
    "revolutionize": "change", "revolutionary": "notable", "delve": "look",
    "unlock": "release", "game-changing": "significant",
    "world-class": "strong",
}

_ACRONYM_EXPANSIONS = {
    "ARR": "Annual Recurring Revenue", "NRR": "Net Revenue Retention",
    "CAC": "Customer Acquisition Cost", "LTV": "Lifetime Value",
    "SLA": "Service Level Agreement", "KPI": "Key Performance Indicator",
    "CRM": "Customer Relationship Management",
    "ERP": "Enterprise Resource Planning", "QA": "Quality Assurance",
    "UAT": "User Acceptance Testing", "TAT": "Turnaround Time",
    "SOP": "Standard Operating Procedure", "ROI": "Return on Investment",
    "FTE": "Full Time Equivalent", "OKR": "Objective and Key Result",
}

_MINOR = {"a", "an", "the", "and", "but", "or", "nor", "for", "as", "at", "by",
          "in", "of", "off", "on", "per", "to", "up", "via", "with", "from"}


def _sentence_case(heading: str, allowlist: set[str]) -> str:
    words = heading.split()
    out = []
    for i, w in enumerate(words):
        bare = w.strip(".,:;!?()[]'\"")
        if i == 0 or bare in allowlist or re.fullmatch(r"[A-Z]{2,5}", bare):
            out.append(w)
        else:
            out.append(w[:1].lower() + w[1:])
    return " ".join(out)


def _replace_once(text: str, old: str, new: str) -> str:
    if old and old in text:
        return text.replace(old, new, 1)
    return text


# --- per-rule fixers: (text, violation, ctx) -> text -----------------------

def _fix_h1(text: str, v: Violation, ctx: dict) -> str:
    sentence = v.span
    for m in re.finditer(r"\b(and|or)\b", sentence, re.IGNORECASE):
        before = sentence[: m.start()]
        if "," in before and not before.rstrip().endswith(","):
            fixed = (before.rstrip() + ", " + sentence[m.start():])
            return _replace_once(text, sentence, fixed)
    return text


def _fix_h2(text: str, v: Violation, ctx: dict) -> str:
    return _replace_once(text, v.span, _sentence_case(v.span, ctx["allowlist"]))


def _fix_h4(text: str, v: Violation, ctx: dict) -> str:
    span = v.span.strip()
    # "3 critical" -> "three critical". The following word is part of the span
    # precisely so this targets the violating digit and not some other digit
    # elsewhere in the document (which previously turned a compliant "3 days"
    # into "three days" and made the normalizer oscillate forever).
    m = re.fullmatch(r"(\d)\s+([A-Za-z][\w-]*)", span)
    if m:
        return _replace_once(text, span, f"{_NUM_WORD[int(m.group(1))]} {m.group(2)}")
    if re.fullmatch(r"\d", span):                       # bare digit -> word
        return re.sub(rf"(?<![\d.,%$£€-])\b{span}\b(?![\d.,%-])",
                      _NUM_WORD[int(span)], text, count=1)
    m = re.fullmatch(r"(?i)(\w+)\s+(\w+)", span)        # "three days" -> "3 days"
    if m and m.group(1).lower() in _WORD_NUM:
        return _replace_once(text, span,
                             f"{_WORD_NUM[m.group(1).lower()]} {m.group(2)}")
    if span.lower() in _WORD_NUM:                        # "twelve" -> "12"
        return re.sub(rf"\b{re.escape(span)}\b", str(_WORD_NUM[span.lower()]),
                      text, count=1, flags=re.IGNORECASE)
    return text


def _fix_h5(text: str, v: Violation, ctx: dict) -> str:
    number = v.span.replace("%", "").strip()
    return _replace_once(text, v.span, f"{number} percent")


def _fix_h6(text: str, v: Violation, ctx: dict) -> str:
    span = v.span
    m = re.fullmatch(r"(?i)([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", span)
    if m:
        month = _MONTH_ABBR.get(m.group(1).capitalize(), m.group(1).capitalize())
        return _replace_once(text, span, f"{int(m.group(2))} {month} {m.group(3)}")
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", span)
    if m:
        day, mon, year = int(m.group(1)), int(m.group(2)), m.group(3)
        year = year if len(year) == 4 else "20" + year
        return _replace_once(text, span,
                             f"{day} {_MONTH_BY_NUM.get(mon, 'January')} {year}")
    m = re.fullmatch(r"(?i)(\d{1,2})(?:st|nd|rd|th)\s+(\w+)", span)
    if m:
        return _replace_once(text, span, f"{int(m.group(1))} {m.group(2)}")
    return text


def _fix_h7(text: str, v: Violation, ctx: dict) -> str:
    span = v.span
    if span.startswith("http"):
        cleaned = _replace_once(text, span, "").replace("  ", " ")
        return re.sub(r"\s+([.,])", r"\1", cleaned)
    m = re.fullmatch(r"\((?:see\s+)?([A-Za-z][\w&.\- ]*?)\s*,?\s*((?:19|20)\d{2})\)",
                     span)
    if m:
        return _replace_once(text, span, f"({m.group(1).strip()}, {m.group(2)})")
    # "Smith (2025)" — author outside the parentheses. Real model prose writes
    # citations this way; the span the detector reports is only "(2025)", so
    # the author has to be recovered from the preceding token.
    m = re.fullmatch(r"\(((?:19|20)\d{2})\)", span)
    if m:
        year = m.group(1)
        author = re.search(rf"\b([A-Z][A-Za-z&.\-]+)\s+\({year}\)", text)
        if author:
            return _replace_once(text, f"{author.group(1)} ({year})",
                                 f"({author.group(1)}, {year})")
        return _replace_once(text, span, year)  # a bare year needs no parentheses
    return text


def _fix_h8(text: str, v: Violation, ctx: dict) -> str:
    span = v.span
    key = span.lower().replace("’", "'")
    if key in _CONTRACTIONS:
        repl = _CONTRACTIONS[key]
        if span[0].isupper():
            repl = repl[:1].upper() + repl[1:]
        return _replace_once(text, span, repl)
    return text


def _fix_h9(text: str, v: Violation, ctx: dict) -> str:
    """Split an over-long sentence at the comma nearest its midpoint."""
    sentence = v.span
    commas = [m.start() for m in re.finditer(r",\s", sentence)]
    if not commas:
        raise NormalizationError(
            f"sentence over {ctx['h9_limit']} words with no comma to split on: "
            f"{sentence[:80]}..."
        )
    mid = len(sentence) // 2
    pivot = min(commas, key=lambda c: abs(c - mid))
    head, tail = sentence[:pivot].rstrip(), sentence[pivot + 1:].strip()
    tail = tail[:1].upper() + tail[1:]
    return _replace_once(text, sentence, f"{head}. {tail}")


def _fix_h10(text: str, v: Violation, ctx: dict) -> str:
    span = v.span
    repl = _HYPE.get(span.lower(), "use")
    if span[0].isupper():
        repl = repl[:1].upper() + repl[1:]
    return re.sub(rf"\b{re.escape(span)}\b", repl, text, count=1)


def _fix_h11(text: str, v: Violation, ctx: dict) -> str:
    return re.sub(r"(?:\s-{1,2}\s|\s–\s|\s—\s)", "—", text, count=1)


def _fix_h12(text: str, v: Violation, ctx: dict) -> str:
    item = v.span
    fixed = item.rstrip(".!?;:")
    fixed = fixed[:1].upper() + fixed[1:]
    return _replace_once(text, item, fixed)


def _fix_h13(text: str, v: Violation, ctx: dict) -> str:
    acr = v.span
    expansion = _ACRONYM_EXPANSIONS.get(acr)
    if not expansion:
        raise NormalizationError(
            f"acronym {acr!r} has no committed expansion; add it to "
            "_ACRONYM_EXPANSIONS or regenerate the draft"
        )
    return re.sub(rf"\b{re.escape(acr)}\b", f"{expansion} ({acr})",
                  text, count=1)


def _fix_h14(text: str, v: Violation, ctx: dict) -> str:
    span = v.span
    if re.fullmatch(r"I", span):
        return re.sub(r"\bI\b", "We", text, count=1)
    if span.lower() == "my":
        return re.sub(r"\bmy\b", "our", text, count=1, flags=re.IGNORECASE)
    if span.lower().startswith("one "):
        return _replace_once(text, span, "you " + span.split(" ", 1)[1])
    if span.lower() == "the reader":
        return _replace_once(text, span, "you")
    return text


_FIXERS = {"H1": _fix_h1, "H2": _fix_h2, "H4": _fix_h4, "H5": _fix_h5,
           "H6": _fix_h6, "H7": _fix_h7, "H8": _fix_h8, "H9": _fix_h9,
           "H10": _fix_h10, "H11": _fix_h11, "H12": _fix_h12,
           "H13": _fix_h13, "H14": _fix_h14}


def _deterministic_violations(text: str, rubric: dict,
                              allowlist: set[str]) -> list[tuple[dict, Violation]]:
    doc = Document.parse(text)
    found = []
    for rule in rubric["rules"]:
        if rule["detector"] != "deterministic":
            continue
        detector = DETERMINISTIC_DETECTORS.get(rule["id"])
        if detector is None:
            continue
        violations = (detector(doc, rule, allowlist) if rule["id"] == "H2"
                      else detector(doc, rule))
        found.extend((rule, v) for v in violations)
    return found


def normalize(text: str, rubric: dict | None = None) -> str:
    """Repair to zero deterministic violations, or raise."""
    rubric = rubric or load_rubric("meridian")
    allowlist = set(rubric.get("proper_noun_allowlist", []))
    h9_limit = next(r for r in rubric["rules"] if r["id"] == "H9")["limit"]
    ctx = {"allowlist": allowlist, "h9_limit": h9_limit}

    seen: set[str] = set()
    for _ in range(MAX_PASSES):
        found = _deterministic_violations(text, rubric, allowlist)
        if not found:
            return text if text.endswith("\n") else text + "\n"
        # Oscillation guard: a fixer that undoes an earlier fixer's work will
        # revisit a document state. Fail loudly rather than spin to the pass
        # limit and report a misleading "did not converge".
        if text in seen:
            raise NormalizationError(
                "normalizer oscillated: two fixers are undoing each other. "
                f"Current first violation: {found[0][0]['id']} "
                f"span={found[0][1].span[:60]!r}"
            )
        seen.add(text)
        rule, violation = found[0]
        fixer = _FIXERS.get(rule["id"])
        if fixer is None:
            raise NormalizationError(f"no fixer for {rule['id']}")
        new_text = fixer(text, violation, ctx)
        if new_text == text:
            raise NormalizationError(
                f"{rule['id']} fixer made no progress on span {violation.span[:80]!r}"
            )
        text = new_text

    remaining = _deterministic_violations(text, rubric, allowlist)
    raise NormalizationError(
        f"did not converge in {MAX_PASSES} passes; "
        f"{len(remaining)} violations remain: "
        f"{[(r['id'], v.span[:40]) for r, v in remaining[:5]]}"
    )


def normalize_file(src: Path, dst: Path, rubric: dict | None = None) -> dict:
    rubric = rubric or load_rubric("meridian")
    before = score_document(src.read_text("utf-8"), rubric, MockH3Provider())
    text = normalize(src.read_text("utf-8"), rubric)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    after = score_document(text, rubric, MockH3Provider())
    if after.deterministic_raw != 0:
        raise NormalizationError(
            f"{src.name}: normalizer returned a non-zero document "
            f"({after.deterministic_raw} deterministic violations)"
        )
    return {
        "source": src.name,
        "output": dst.name,
        "deterministic_before": before.deterministic_raw,
        "deterministic_after": after.deterministic_raw,
        "h3_before": before.llm_raw,
        "h3_after": after.llm_raw,
    }
