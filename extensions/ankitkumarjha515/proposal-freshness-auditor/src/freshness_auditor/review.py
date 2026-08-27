"""The human gate.

Detection says what *looks* stale. This module lets a person decide, one
finding at a time, what actually gets changed — and groups the approved
corrections into batches the apply stage can execute.

Two rules drive the design:

* **Rejecting one finding does not discard the rest.** Every decision is
  recorded against a single finding id and touches nothing else.
* **A batch costs money.** One SuperDocs operation covers up to 25 sections
  of targeted edits in a single request, so corrections are grouped by
  document, not issued per finding. A document with nothing approved
  produces no batch at all rather than an empty one — an empty batch would
  be a paid request that changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .detect import Finding

#: One SuperDocs operation covers up to this many sections of targeted
#: edits in a single request, so it is the natural batch ceiling.
MAX_ITEMS_PER_BATCH = 25

#: Findings at or below this confidence are rendered with a warning marker.
#: They are never suppressed — surfacing beats silently dropping — but a
#: reviewer should look harder at them.
LOW_CONFIDENCE = 0.75


class ReviewError(Exception):
    """Base class for review errors."""


class UnknownFindingError(ReviewError):
    """Raised when a decision names a finding the session does not hold."""


class Decision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ReviewItem:
    """A finding plus the human's decision about it.

    `Finding` is frozen and stays untouched — it is what the detector saw.
    The decision is what a person said about it. Keeping them separate means
    a re-run of detection can be compared against prior decisions.
    """

    finding: Finding
    decision: Decision = Decision.PENDING
    note: str | None = None


@dataclass(frozen=True)
class DocumentBatch:
    """Approved corrections for one document, sized for one operation."""

    doc_id: str
    items: tuple[ReviewItem, ...]
    part: int = 1  # 1-based; >1 when a document needed splitting
    of_parts: int = 1

    def chunk_ids(self) -> list[str]:
        """Chunk ids touched by this batch, in order, without duplicates.

        A chunk id may be ``None`` when the source HTML carried no
        ``data-chunk-id`` (local files before upload); those are skipped.
        """
        seen: list[str] = []
        for item in self.items:
            cid = item.finding.evidence.chunk_id
            if cid is not None and cid not in seen:
                seen.append(cid)
        return seen


class ReviewSession:
    """Holds findings and the decisions made about them.

    Order is stable: findings keep the order they were supplied in, which
    is itself deterministic from detection. Nothing user-visible depends on
    dict or set iteration order.
    """

    def __init__(self, items: list[ReviewItem]) -> None:
        self._items: list[ReviewItem] = list(items)
        self._index: dict[str, int] = {
            item.finding.id: i for i, item in enumerate(self._items)
        }

    @classmethod
    def from_findings(cls, findings: list[Finding]) -> "ReviewSession":
        return cls([ReviewItem(finding=f) for f in findings])

    # -- reading ---------------------------------------------------------

    def items(self) -> list[ReviewItem]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(list(self._items))

    def get(self, finding_id: str) -> ReviewItem:
        i = self._index.get(finding_id)
        if i is None:
            raise UnknownFindingError(
                f"no finding with id {finding_id!r} in this review session — "
                f"use an id from session.items(), or rebuild the session from "
                f"a fresh detection run"
            )
        return self._items[i]

    def pending(self) -> list[ReviewItem]:
        return [i for i in self._items if i.decision is Decision.PENDING]

    def approved(self) -> list[ReviewItem]:
        return [i for i in self._items if i.decision is Decision.APPROVED]

    def rejected(self) -> list[ReviewItem]:
        return [i for i in self._items if i.decision is Decision.REJECTED]

    def is_complete(self) -> bool:
        return not self.pending()

    def summary(self) -> dict[str, int]:
        return {
            "total": len(self._items),
            "pending": len(self.pending()),
            "approved": len(self.approved()),
            "rejected": len(self.rejected()),
        }

    # -- deciding --------------------------------------------------------

    def _set(self, finding_id: str, decision: Decision, note: str | None) -> None:
        i = self._index.get(finding_id)
        if i is None:
            raise UnknownFindingError(
                f"cannot record a decision for unknown finding id "
                f"{finding_id!r} — use an id from session.items()"
            )
        # Rebuilds exactly one slot. Every other item keeps its own object,
        # so no other decision or note can move.
        self._items[i] = replace(self._items[i], decision=decision, note=note)

    def approve(self, finding_id: str, note: str | None = None) -> None:
        self._set(finding_id, Decision.APPROVED, note)

    def reject(self, finding_id: str, note: str | None = None) -> None:
        self._set(finding_id, Decision.REJECTED, note)

    def reset(self, finding_id: str) -> None:
        self._set(finding_id, Decision.PENDING, None)

    def approve_all(self) -> None:
        for item in list(self._items):
            self.approve(item.finding.id)

    def reject_all(self, note: str | None = None) -> None:
        for item in list(self._items):
            self.reject(item.finding.id, note)


def build_batches(
    session: ReviewSession,
    max_items_per_batch: int = MAX_ITEMS_PER_BATCH,
) -> list[DocumentBatch]:
    """Group approved items into one batch per document.

    Documents with no approved items yield no batch. A document with more
    approved items than `max_items_per_batch` splits into several parts,
    deterministically and without losing any item.
    """
    if max_items_per_batch < 1:
        raise ValueError(
            f"max_items_per_batch must be at least 1, got {max_items_per_batch} — "
            f"pass a positive batch size or omit it to use the default of "
            f"{MAX_ITEMS_PER_BATCH}"
        )

    by_doc: dict[str, list[ReviewItem]] = {}
    for item in session.items():
        if item.decision is Decision.APPROVED:
            by_doc.setdefault(item.finding.doc_id, []).append(item)

    batches: list[DocumentBatch] = []
    for doc_id in sorted(by_doc):
        items = by_doc[doc_id]
        chunks = [
            items[i : i + max_items_per_batch]
            for i in range(0, len(items), max_items_per_batch)
        ]
        for n, part_items in enumerate(chunks, start=1):
            batches.append(
                DocumentBatch(
                    doc_id=doc_id,
                    items=tuple(part_items),
                    part=n,
                    of_parts=len(chunks),
                )
            )
    return batches


# -- rendering -----------------------------------------------------------


#: Scale words that must survive a replacement. If the stale text says
#: "3.2 million" and the ledger's canonical value is the bare number 4.1,
#: replacing one with the other yields "4.1 beneficiaries" — a corrupted
#: sentence. The replacement has to carry the same scale word.
_SCALE_WORDS = ("billion", "million", "thousand", "bn", "m", "k")


def canonical_replacement(stated_value: str, canonical_value: str) -> str:
    """The text that should replace the stale text, like for like.

    Mirrors the scale word of the value being replaced, so a magnitude is
    never silently dropped. Only fires when the canonical value is a bare
    number and the stale text carried a scale word — if the canonical value
    already states its own scale, it is used verbatim.
    """
    canon = str(canonical_value).strip()
    stated = str(stated_value).strip()

    # Canonical already carries a scale word: trust it as written.
    if any(w in canon.lower().split() or canon.lower().endswith(w)
           for w in _SCALE_WORDS):
        return canon
    # Canonical is not a bare number (e.g. "March 2026"): use it as written.
    if not canon.replace(",", "").replace(".", "").isdigit():
        return canon

    # Mirror thousands separators. A proposal that says "1,200 staff"
    # should not come back saying "1450 staff" — the correction would be
    # right and the document would look sloppy, which is the sort of thing
    # a bid manager notices before the reader does.
    if "," in stated and "," not in canon and canon.isdigit() and len(canon) > 3:
        canon = f"{int(canon):,}"

    low = stated.lower()
    for word in _SCALE_WORDS:
        # Word form ("3.2 million") or suffix form ("3.2m").
        if f" {word}" in low or (low.endswith(word) and low[:-len(word)].strip()):
            spaced = f" {word}" in low
            return f"{canon} {word}" if spaced else f"{canon}{word}"
    return canon


def _mark_span(sentence: str, quote: str) -> str:
    """Show the matched span inside its sentence with >>markers<<.

    ASCII markers on purpose: Windows consoles default to cp1252, which
    cannot encode the prettier glyphs, and a reviewer should never see a
    UnicodeEncodeError instead of a finding.
    """
    i = sentence.find(quote)
    if i < 0:
        return sentence
    return f"{sentence[:i]}>>{quote}<<{sentence[i + len(quote):]}"


def render_finding(item: ReviewItem, index: int | None = None) -> str:
    """Everything a reviewer needs to decide without trusting the tool.

    Provenance is not decoration. "Change 1,200 to 1,450" is an instruction
    to obey; "change 1,200 to 1,450, per the HR headcount report, as of
    2026-07-01" is a claim a human can check. Without the source and the
    date, the human gate is theatre.

    The quoted sentence is data. It may contain anything at all, including
    text that reads like an instruction to a system; it is displayed and
    never acted upon.
    """
    f = item.finding
    head = f"[{index}] " if index is not None else ""
    flag = "  [!] LOW CONFIDENCE" if f.confidence <= LOW_CONFIDENCE else ""
    loc = f"element {f.evidence.element_index}"
    if f.evidence.chunk_id:
        loc += f", chunk {f.evidence.chunk_id}"

    return "\n".join(
        [
            f"{head}{f.doc_id} — {f.fact_id}   [{item.decision.value}]   id {f.id}",
            f"    stale value : {f.stated_value!r}   (retired {f.matched_prior.retired_on})",
            f"    should be   : {canonical_replacement(f.stated_value, f.canonical_value)!r}",
            f"    per         : {f.source}, as of {f.as_of}",
            f"    match       : {f.match_type}   confidence {f.confidence:.2f}{flag}",
            f"    location    : {loc}, chars {f.evidence.start}-{f.evidence.end}",
            f"    context     : {_mark_span(f.evidence.sentence, f.evidence.quote)}",
        ]
        + ([f"    note        : {item.note}"] if item.note else [])
    )


def render_summary(session: ReviewSession) -> str:
    """A count of what happened. Never overstates."""
    s = session.summary()
    lines = [
        f"{s['total']} finding(s): "
        f"{s['approved']} approved, {s['rejected']} rejected, {s['pending']} pending"
    ]
    batches = build_batches(session)
    if batches:
        docs = len({b.doc_id for b in batches})
        lines.append(
            f"{len(batches)} batch(es) across {docs} document(s) "
            f"— {len(batches)} operation(s) will be spent"
        )
    else:
        lines.append("no batches — nothing approved, so no operations will be spent")
    return "\n".join(lines)
