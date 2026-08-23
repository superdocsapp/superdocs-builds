"""The tiers, in order, over every block in the document.

    tier 1 · patterns   free, deterministic, exact. Identifiers with a shape.
    tier 2 · GLiNER     local NER for names and addresses. Baked in, on by
                        default — no network, same answer every run.
    tier 3 · LLM        names in prose, addresses, and privileged passages.

Every block, not just the body: the blocks come from `blocks.py`, which reads
the `.docx` package, so headers, footers, footnotes, comments and tracked
deletions arrive with the same kind of id. A body-only pane passes a document
carrying an SSN inside a tracked deletion and reports it clean.

Tier 3 is skipped only for a block tier 1 claimed *entirely* — "this paragraph
has an email" says nothing about whether it also names a patient.

See extensions/redaction-pane/README.md § "How it finds things".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import llm as llm_tier
from .patterns import Span, find, sentence_around


@dataclass(frozen=True, slots=True)
class Candidate:
    """One thing to ask a human about."""

    chunk_id: str
    part_type: str
    """`body`, `header`, `footer`, `footnote`, `endnote`, `comment` or
    `tracked_del`. Shown on the row — "this SSN is inside a tracked deletion" is
    a finding a reviewer would otherwise never see."""
    span: Span
    sentence: str
    """The surrounding sentence, which makes confirm/dismiss a judgement rather
    than a guess."""

    @property
    def key(self) -> str:
        """What makes two findings the same question — NOT the offset. Redaction
        replaces every occurrence, so keying on offset would ask the same
        question three times, and would break on the first edit as offsets move.
        `part_type` stays in the key because a name in the body is removable in
        place and the same name in a tracked deletion is not."""
        return f"{self.part_type}:{self.span.category}:{self.span.text}"


@dataclass
class ScanResult:
    candidates: list[Candidate] = field(default_factory=list)
    llm_blocks: int = 0
    dropped_unverifiable: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tiers: list[str] = field(default_factory=list)
    """Which tiers actually ran. Reported to the pane so a scan with the LLM
    switched off cannot be mistaken for a scan that found nothing."""
    llm_error: str = ""
    """Set when tier 3 was configured and failed mid-scan. The scan still returns
    tiers 1 and 2; this is how the pane says the rest was not looked for."""


NER_LABELS = ["person", "address"]
"""What tier 2 is asked for, and nothing else. `organization` is deliberately not
requested — a company name is not personal data, and asking for it puts the
counterparty on every paragraph. Dates and identifiers have shapes and belong to
tier 1, which is free and exact."""


def scan(
    blocks: list[tuple[str, str, str]],
    *,
    llm: Any | None = None,
    locate: Callable[[str, str], tuple[int, int] | None] | None = None,
    ner: Any | None = None,
    ner_threshold: float = 0.5,
) -> ScanResult:
    """`[(chunk_id, part_type, text)]` → candidates. Order inside a block is
    document order; order across blocks is the package reader's, which is
    document order too."""
    result = ScanResult()
    result.tiers.append("patterns")
    if ner is not None:
        result.tiers.append("ner")
    if llm is not None:
        result.tiers.append("llm")

    for chunk_id, part_type, text in blocks:
        if not text or not text.strip():
            continue
        spans: list[Span] = find(text)

        if ner is not None:
            for span in _ner_spans(ner, text, ner_threshold):
                if not any(hit.start < span.end and span.start < hit.end for hit in spans):
                    spans.append(span)

        if llm is not None and locate is not None:
            try:
                found = llm_tier.scan_block(text, llm=llm, locate=locate)
            except Exception as exc:
                # Degrade, never crash. A provider outage or expired key must not
                # take down the one button in the pane — the pattern and NER
                # findings are already in hand. `llm = None` stops it here rather
                # than repeating the failed call once per paragraph.
                result.llm_error = f"{type(exc).__name__}: {exc}"[:400]
                llm = None
                if "llm" in result.tiers:
                    # It did not run, so stop saying it did — keeps "nothing
                    # found" honest.
                    result.tiers.remove("llm")
            else:
                result.llm_blocks += 1
                result.dropped_unverifiable += found.dropped
                result.input_tokens += found.input_tokens
                result.output_tokens += found.output_tokens
                for span in found.spans:
                    if not any(hit.start < span.end and span.start < hit.end for hit in spans):
                        spans.append(span)

        for span in sorted(spans, key=lambda item: item.start):
            result.candidates.append(
                Candidate(
                    chunk_id=chunk_id,
                    part_type=part_type,
                    span=span,
                    sentence=sentence_around(text, span.start, span.end),
                )
            )
    return result


def _ner_spans(ner: Any, text: str, threshold: float = 0.5) -> list[Span]:
    """Tier 2: names and addresses, locally, with offsets the client verifies.
    Everything it returns is `personal` — the only two labels it is asked for
    (see `NER_LABELS`)."""
    from .patterns import PERSONAL

    spans: list[Span] = []
    for entity in ner.extract(text, NER_LABELS, threshold=threshold):
        spans.append(
            Span(
                start=entity.start,
                end=entity.end,
                text=text[entity.start : entity.end],
                kind=entity.label,
                category=PERSONAL,
                detector="ner",
                confidence=float(getattr(entity, "score", 0.5)),
            )
        )
    return spans
