"""The analyst: turn the brief + evidence pile into a proposal.

This is where the engine "thinks": it orders the evidence following the brief's
argument, writes each exhibit's cover-page text (what it proves), paginates, and
plans in-brief citations. The deterministic pipeline always works with no API
key; when a CrewAI crew is configured (``crew.write_covers``), its CoverWriter
agent produces the human-authored cover text instead.

Everything downstream — covers, index, packet, citations — is derived from the
``ExhibitSet`` this module builds, so any late insertion renumbers every artifact
that depends on position.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .citations import _keywords, plan_citations
from .model import Citation, Exhibit, ExhibitSet
from .order import EvidenceItem, propose_order
from .paging import paginate_set

# A cover writer is (title, content) -> "what it proves" sentence.
CoverWriter = Callable[[str, str], str]


@dataclass
class Proposal:
    """The analyst's output: an ordered, paginated exhibit set and its citations."""

    set: ExhibitSet
    citations: list[Citation]
    order_note: str

    def repropose(self, brief: str) -> "Proposal":
        """After the set changed (e.g. a late insertion renumbered it), recompute
        everything derived from position — page numbers and in-brief citations —
        and update this proposal in place. Returns self for chaining."""
        paginate_set(self.set)
        self.citations = plan_citations(self.set, brief)
        self.order_note = "Re-paginated and re-cited after the set changed."
        return self


def propose(brief: str, items: list[EvidenceItem],
            cover_writer: CoverWriter | None = None) -> Proposal:
    """Build a full proposal from the brief and the evidence pile."""
    ordered = propose_order(brief, items)
    writer = cover_writer or _default_cover_writer

    set_ = ExhibitSet()
    for item in ordered:
        title = _human_title(item.source)
        set_.add(
            source=Path(item.source),
            title=title,
            proves=writer(title, item.text),
            content=item.text,
        )
    paginate_set(set_)
    return Proposal(
        set=set_,
        citations=plan_citations(set_, brief),
        order_note=_order_note(ordered),
    )


def replan(set_: ExhibitSet, brief: str) -> Proposal:
    """Compatibility wrapper around :meth:`Proposal.repropose` for callers that
    want a fresh Proposal object. Prefer ``proposal.repropose(brief)``."""
    return Proposal(set=set_, citations=[], order_note="").repropose(brief)


def _human_title(source: str) -> str:
    base = Path(source).name  # strip any directory prefix
    base = re.sub(r"\.(pdf|docx?|md|txt|html?|rtf)$", "", base, flags=re.I)
    base = re.sub(r"[^A-Za-z0-9 ]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return " ".join(w.capitalize() for w in base.split()[:8]) or "Exhibit"


# A "Label: value" line, the shape most structured evidence (passports, bank
# statements, tax returns) arrives in.
_KV_RE = re.compile(
    r"(?im)^\s*([A-Za-z][A-Za-z0-9 &()'/.\-]{1,40}?)\s*:\s*(.{3,120})\s*$"
)


def _default_cover_writer(title: str, content: str) -> str:
    """Deterministic cover text from the exhibit's own content.

    Always grammatical and grounded — never a list of truncated keyword stems.
    Documents that are a run of "Label: value" lines (passports, bank
    statements, tax returns) are summarised by their most concrete field: value
    pairs; prose documents by quoting their most evidential sentence; anything
    else falls back to a clean, title-grounded line. A CrewAI CoverWriter agent
    replaces this line when configured.
    """
    pairs = _key_value_pairs(content)
    if len(pairs) >= 2:
        top = _rank_pairs(pairs)[:3]
        listing = ", ".join(f"{label}: {value}" for label, value in top)
        if len(listing) <= 200:
            return f"Evidences {listing}."
    clause = _best_clause(content)
    if clause:
        return f"Evidences: “{clause}”"
    return f"{title} — supporting evidence for this application."


def _key_value_pairs(content: str) -> list[tuple[str, str]]:
    """``Label: value`` lines in the content, cleaned and value-capped."""
    pairs: list[tuple[str, str]] = []
    for m in _KV_RE.finditer(content):
        label = m.group(1).strip().rstrip(":")
        value = re.sub(r"\s+", " ", m.group(2)).strip(" \"'")
        if not label or not value:
            continue
        # A value that is itself an ALL-CAPS heading is boilerplate, not a fact.
        if value.isupper() and len(value) > 24:
            continue
        pairs.append((label, _truncate_words(value, 12)))
    return pairs


def _rank_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Most concrete pairs first: digit groups (dates, amounts, numbers) and
    currency win; ties keep document order so a readable label order (e.g.
    ``Date of Birth`` before ``Date of Issue``) survives."""
    def key(p: tuple[str, str]) -> tuple[int, int]:
        _label, value = p
        digits = len(re.findall(r"\d", value))
        money = len(re.findall(r"[$€£₹]", value))
        return (-(digits + 2 * money), 0)
    return sorted(pairs, key=key)


def _best_clause(content: str) -> str | None:
    """The exhibit's most evidential clause, cleaned and capped.

    Prefers the document's own quoted voice (support letters quote their
    authors), then plain sentences; markdown headings, list markers and photo
    captions are stripped so the line reads as a fact, never a heading or a
    fragment. Concrete clauses (dates, amounts) outrank general prose.
    """
    candidates = _quoted_clauses(content) + _plain_clauses(content)
    if not candidates:
        return None

    def score(s: str) -> int:
        digits = len(re.findall(r"\d", s))
        money = len(re.findall(r"[$€£₹]", s))
        length = len(s)
        quoted = s[:1] in {'"', "“"}
        caption = 3 if re.match(r"^[A-Za-z ]{2,30}:", s) else 0
        return (
            2 * digits + 2 * money
            + (3 if quoted else 0)
            + (2 if 25 <= length <= 130 else 0)
            - (4 if length < 20 else 0)
            - 2 * len(re.findall(r"[()]", s))
            - caption
        )

    return _truncate_words(max(candidates, key=score), 30)


def _quoted_clauses(content: str) -> list[str]:
    """Quoted spans in the content, each re-split into its own sentence so a
    multi-sentence letter quote yields separate, quotable clauses."""
    clauses: list[str] = []
    for m in re.finditer(r'["“]([^"”]{15,220})["”]', content):
        span = re.sub(r"\s+", " ", m.group(1))
        for s in re.split(r"(?<=[.!?])\s+", span):
            s = s.strip(' "“”\'')
            if 15 <= len(s) <= 200 and not s.isupper():
                clauses.append(s)
    return clauses


def _plain_clauses(content: str) -> list[str]:
    """Sentences with markdown headings, list markers and photo captions
    stripped, so a fact reads as a fact rather than a heading or fragment."""
    text = re.sub(r"(?im)^#+\s+.*$", "", content)
    text = re.sub(r"(?im)^\s*(?:\d+[.)]|\*|-)\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    clauses: list[str] = []
    for s in re.split(r"(?<=[.!?\"'”’])\s+", text):
        s = s.strip(' "“”’\'')
        s = re.sub(r"^photo[-_][A-Za-z0-9]+\.\w+\s*[—–-]\s*", "", s)
        if 15 <= len(s) <= 200 and not s.isupper() and s[:1].isalpha():
            clauses.append(s)
    return clauses


def _truncate_words(text: str, max_words: int) -> str:
    """Cap a clause at ``max_words`` on word boundaries, with an ellipsis."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,;:") + "…"


def _order_note(ordered: list[EvidenceItem]) -> str:
    return (
        f"Ordered {len(ordered)} pieces of evidence to follow the brief's "
        "argument; evidence not touched by the brief is appended last."
    )
