"""The two-signal structural-integrity checker (design doc §16) — the
direct motivation is a documented, real risk: the SuperDocs web editor was
observed silently dropping ~60% of unrelated content on an edit instruction
(see PROGRESS.md, and the plan's Appendix A). This runs on every completed
batch at zero additional SuperDocs cost — it only reads data already
returned by the mutating call it's checking.

Flags if *either* signal fires — the same structural echo of Task 1's
two-signal injection detector: one signal alone either false-positives (a
legitimate large edit) or misses the documented failure mode.
"""

from __future__ import annotations

import html as html_module
import re
from typing import NamedTuple

_HEADING_PATTERN = re.compile(r"<h[1-6][ >]", re.IGNORECASE)
_TAG_PATTERN = re.compile(r"<[^>]+>")


class IntegrityResult(NamedTuple):
    passed: bool
    reason: str | None


def _visible_text_length(html: str) -> int:
    return len(_TAG_PATTERN.sub(" ", html or "").strip())


def _heading_count(html: str) -> int:
    return len(_HEADING_PATTERN.findall(html or ""))


def _duplicate_block(html: str, min_len: int = 40) -> str | None:
    """A substantial block of visible text repeated verbatim anywhere in
    the document — observed live: SuperDocs placed the same intro
    paragraph under both Project Details and Next Steps. This is the
    milder sibling of the documented ~60% content-loss bug this module
    already guards against — instead of dropping content on an edit, it
    sometimes duplicates it into an unrelated section rather than losing
    it. Short blocks are excluded deliberately: a repeated short phrase
    ("Our total budget is $45,000.") can legitimately echo across a
    summary and a details section; a full paragraph never should."""
    blocks = re.findall(
        r"<(?:p|div|li)[^>]*>(.*?)</(?:p|div|li)>", html or "", re.IGNORECASE | re.DOTALL
    )
    seen: set[str] = set()
    for b in blocks:
        text = re.sub(r"\s+", " ", _TAG_PATTERN.sub(" ", b)).strip().lower()
        if len(text) < min_len:
            continue
        if text in seen:
            return text
        seen.add(text)
    return None


_PLACEHOLDER_RE = re.compile(r"please\s+fill|\bTBD\b|\bTODO\b|\bFIXME\b|\[insert", re.IGNORECASE)
_TABLE_COUNT_RE = re.compile(r"<table", re.IGNORECASE)
_BLOCK_TEXT_RE = re.compile(r"<(?:p|li)[^>]*>(.*?)</(?:p|li)>", re.IGNORECASE | re.DOTALL)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _words(text: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split() if len(w) > 2}


def _near_duplicate_block(html: str, threshold: float = 0.75) -> str | None:
    """A block that restates one already in the document.

    `_duplicate_block` only catches verbatim repeats, but a retry never
    repeats itself exactly — it rephrases. One live export carried four
    variants of the same sentence ("...and we'll see you next time", "...and
    we will see you next time", "...and look forward to seeing you next
    time"), each a fresh paragraph that verbatim matching waved through."""
    blocks: list[str] = []
    for raw in _BLOCK_TEXT_RE.findall(html or ""):
        text = re.sub(r"<[^>]+>", " ", raw)
        text = html_module.unescape(re.sub(r"\s+", " ", text)).strip()
        # Compared SENTENCE by sentence, not block by block: a restatement
        # frequently lands inside the SAME paragraph as the original ("We
        # will develop a modern, responsive website that allows customers
        # to browse products... We need a modern responsive website where
        # customers can browse products..."), which block-level comparison
        # never sees because it is all one <p>.
        for sentence in _SENTENCE_SPLIT_RE.split(text):
            sentence = sentence.strip()
            if len(sentence) >= 40:
                blocks.append(sentence)
    for i, a in enumerate(blocks):
        wa = _words(a)
        if len(wa) < 5:
            continue
        for b in blocks[i + 1 :]:
            wb = _words(b)
            if not wb:
                continue
            overlap = len(wa & wb) / min(len(wa), len(wb))
            if overlap >= threshold:
                return b[:80]
    return None


def structural_defect(html_before: str, html_after: str) -> str | None:
    """Structural damage detectable from the resulting document alone.

    Needed because SuperDocs sometimes applies an edit itself and reports
    `completed` rather than offering it for approval — a path that skipped
    `validate_proposal` entirely, so placeholders and invented tables were
    written straight into the document with nothing checking them. Confirmed
    from a real export: a "Please fill: Project assumptions and
    dependencies" paragraph and an entire second Project Details table
    carrying "Please fill: Status"."""
    if _PLACEHOLDER_RE.search(html_after or ""):
        m = _PLACEHOLDER_RE.search(html_after)
        return f"document contains placeholder text: {m.group(0)!r}"
    before_tables = len(_TABLE_COUNT_RE.findall(html_before or ""))
    after_tables = len(_TABLE_COUNT_RE.findall(html_after or ""))
    if after_tables > before_tables:
        return f"document gained a table ({before_tables} → {after_tables})"
    dup = _near_duplicate_block(html_after)
    if dup:
        return f"document restates existing content: {dup!r}"
    return None


def check_integrity(
    *,
    html_before: str,
    html_after: str,
    changes: list[dict],
    classification: str,
    removal_expected: bool = False,
) -> IntegrityResult:
    """`removal_expected` exists for forward compatibility (a future
    instruction template that explicitly asks to remove a section) — every
    M3 instruction template only ever asks to add or update a value, never
    to remove one, so M3 always calls this with the default `False`."""

    # Signal A — proportionality of SuperDocs' own reported diff
    # (document_changes.changes — confirmed live under approval_mode=auto;
    # see PROGRESS.md M3). `operation: "create"` is confirmed live for an
    # addition; `"delete"` below is inferred from that same CRUD-style
    # naming, not independently confirmed. If it turns out wrong this check
    # just never fires — Signal B below is the independent, structural
    # backstop that doesn't depend on SuperDocs' own operation labels at all.
    operations = [d.get("operation") for d in changes]
    if (
        not removal_expected
        and classification == "addition"
        and operations
        and all(op == "delete" for op in operations)
    ):
        return IntegrityResult(False, "an addition batch reported only delete operations")
    if classification == "correction" and len(operations) > 3:
        return IntegrityResult(
            False, f"a correction batch touched {len(operations)} chunks — expected a targeted fix"
        )

    # Signal B — an independent full-document scan, deliberately not
    # trusting SuperDocs' own bookkeeping (the documented failure mode is in
    # SuperDocs' own reassembly, so a check that only reads chunk_diffs
    # would share its blind spot).
    headings_before, headings_after = _heading_count(html_before), _heading_count(html_after)
    if headings_after < headings_before and not removal_expected:
        return IntegrityResult(
            False, f"section count dropped {headings_before} -> {headings_after}"
        )

    length_before, length_after = _visible_text_length(html_before), _visible_text_length(html_after)
    if length_before > 0 and length_after < length_before * 0.5 and not removal_expected:
        shrink = 1 - (length_after / length_before)
        return IntegrityResult(False, f"visible text shrank by {shrink:.0%}")

    # Signal C — duplicate content. Independent of A/B: a duplication can
    # pass both the proportionality check (nothing looks deleted) and the
    # heading/length checks (the document only grew), while still being
    # wrong — the same paragraph landed in two places instead of one.
    dup = _duplicate_block(html_after)
    if dup and not removal_expected:
        return IntegrityResult(False, f"duplicate content across sections: {dup[:80]!r}")

    # Verbatim matching above is not enough — a restatement is reworded, so
    # it slips through. Only the auto-apply path checked for that, leaving
    # the ordinary approval path blind: one clean run still exported Scope
    # of Work saying the same thing twice, and the Assumptions paragraph
    # repeated under Next Steps.
    near = _near_duplicate_block(html_after)
    if near and not removal_expected:
        return IntegrityResult(False, f"document restates existing content: {near[:80]!r}")

    return IntegrityResult(True, None)
