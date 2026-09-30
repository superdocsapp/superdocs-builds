"""One scan, end to end: bytes in, rows a human can answer out.

Between `blocks.py` (where text hides) and `pii/engine.py` (how it is found),
this decides which tiers the configuration can run and says so — because "the
scan found nothing" and "tier 3 never ran, no key" produce the same empty list
and must not look the same on screen. Clients are built once and reused.

See extensions/redaction-pane/README.md § "How it finds things".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from service import blocks as block_reader
from service import markers
from service._portable.llm_client import LLMError, build_client
from service._portable.verify import find_quote
from service.pii import engine
from service.review import Candidate as ReviewCandidate
from service.settings import Settings


@dataclass
class Outcome:
    candidates: list[engine.Candidate] = field(default_factory=list)
    coverage: dict[str, int] = field(default_factory=dict)
    """Blocks per part type. The total is `sum(...)` of this — carrying both
    meant two numbers that could disagree."""
    tiers: list[str] = field(default_factory=list)
    llm_blocks: int = 0
    dropped_unverifiable: int = 0
    """Spans tier 3 returned that aren't in the document at their quoted wording.
    Dropped, and counted here — unverifiable spans and a clean block differ."""
    input_tokens: int = 0
    output_tokens: int = 0
    notes: list[str] = field(default_factory=list)
    """Anything that changed what this scan could see. Shown in the pane."""


class Scanner:
    """Owns the detector clients for the life of the process."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._llm: Any = None
        self._llm_failed: str | None = None
        self._ner: Any = None
        self._ner_failed: str | None = None

    # ── tiers ────────────────────────────────────────────────────────────
    def llm(self) -> Any | None:
        """Tier 3, or None with a reason recorded. A failure degrades the scan,
        never fails it: a typo'd key gets pattern findings and a line saying why
        the rest is missing, not a 500."""
        if not (self.settings.llm_enabled and self.settings.llm_api_key):
            return None
        if self._llm is None and self._llm_failed is None:
            try:
                self._llm = build_client(
                    provider=self.settings.llm_provider,
                    api_key=self.settings.llm_api_key,
                    model=self.settings.llm_model,
                )
            except LLMError as exc:
                self._llm_failed = str(exc)
        return self._llm

    def ner(self) -> Any | None:
        """Tier 2, off unless `GLINER_ENABLED=true` AND the model loads. The flag
        alone is not enough — listing `ner` while the load fails would report a
        document clean on a detector that never ran. The reason is reported, not
        guessed: "install the extra" was wrong when the package was there and the
        model was simply unreachable."""
        if not self.settings.gliner_enabled:
            return None
        if self._ner is None and self._ner_failed is None:
            try:
                from service._portable.ner_gliner import GLiNERClient

                client = GLiNERClient(model_name=self.settings.gliner_model)
                # `load()`, not `is_available`: the property returns True/False
                # and throws away the cause, which is the part worth showing.
                client.load()
                self._ner = client
            except Exception as exc:
                self._ner_failed = _why(exc)
        return self._ner

    # ── the scan ─────────────────────────────────────────────────────────
    def scan(self, data: bytes) -> Outcome:
        found = block_reader.read(data)
        llm = self.llm()
        ner = self.ner()

        result = engine.scan(
            [block.as_tuple() for block in found],
            llm=llm,
            locate=find_quote if llm is not None else None,
            ner=ner,
            ner_threshold=self.settings.gliner_threshold,
        )

        outcome = Outcome(
            candidates=result.candidates,
            coverage=block_reader.coverage(found),
            tiers=result.tiers,
            llm_blocks=result.llm_blocks,
            dropped_unverifiable=result.dropped_unverifiable,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        if self._llm_failed:
            outcome.notes.append(
                f"Tier 3 did not run — names in prose, addresses and privileged "
                f"passages were not looked for. {self._llm_failed}"
            )
        if self._ner_failed:
            outcome.notes.append(f"Tier 2 did not run. {self._ner_failed}")
        if result.llm_error:
            outcome.notes.append(
                "Tier 3 stopped partway — names in prose, addresses and privileged "
                f"passages were not fully looked for. {result.llm_error}"
            )
        return outcome


def _why(exc: BaseException) -> str:
    """The whole exception chain, shortest first. A `ModelUnavailable` says the
    model would not load; its `__cause__` says why — an import error, a missing
    file, an unresolved name — the actionable part a wrapper drops."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        if text and text not in parts:
            parts.append(f"{type(current).__name__}: {text}")
        current = current.__cause__ or current.__context__
    return " ← ".join(parts)[:600] or type(exc).__name__


def candidates(outcome: Outcome) -> list[ReviewCandidate]:
    """Engine findings → the objects the review holds and the pane shows. The
    marker is computed here, once, and carried from this point: pane, Word and
    log all read the same field, so they cannot disagree about what was left."""
    return [
        ReviewCandidate(
            id=str(uuid.uuid4()),
            key=candidate.key,
            chunk_id=candidate.chunk_id,
            part_type=candidate.part_type,
            category=candidate.span.category,
            kind=candidate.span.kind,
            detector=candidate.span.detector,
            confidence=candidate.span.confidence,
            text=candidate.span.text,
            char_start=candidate.span.start,
            char_end=candidate.span.end,
            sentence=candidate.sentence,
            marker=markers.marker(candidate.span.category, candidate.span.kind),
        )
        for candidate in outcome.candidates
    ]
