"""Events are detected from this year's sources, never remembered.

An event fires on a **block** when every phrase group has a phrase present in
that same block, and every group contributes a citation. One block rather than
one document is what keeps it honest: the prior-year set says "control of the
goods transfers to the customer" in the revenue note and carries "Equity share
capital" on the balance sheet, and a document-wide match would read those two as
a business combination.

The vocabulary holds no company name, no acquiree name, no date, no amount and
no standard number. It is a CSV, so a new event is a data edit.

Quarantine runs in both directions. A source carrying an instruction aimed at an
automated reader is reported as quarantined and then not consulted at all -
neither to suppress an event nor to manufacture one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .csvspans import as_records, parse_csv
from .figures import Cite

COMMENT = re.compile(r"<!--(.*?)-->", re.S)
PARAGRAPH_SPLIT = re.compile(rb"\n[ \t]*\n")


@dataclass(frozen=True)
class Block:
    source: str  # corpus-relative path
    byte_start: int
    text: str


@dataclass(frozen=True)
class EventHit:
    event: str
    source: str
    block_text: str
    cites: tuple[Cite, ...]


@dataclass(frozen=True)
class Quarantine:
    source: str
    marker: str
    cite: Cite


class EventDetector:
    def __init__(self, vocabulary: Path, markers: Path) -> None:
        _, records = as_records(parse_csv(vocabulary.read_bytes()))
        self._groups: dict[str, list[list[str]]] = {}
        for record in records:
            name = record["event_name"].text
            groups = [
                [phrase.strip().lower() for phrase in group.split("|") if phrase.strip()]
                for group in record["phrase_groups"].text.split(";;")
            ]
            if not groups or not all(groups):
                raise ValueError(f"{vocabulary.name}: event {name!r} has an empty phrase group")
            self._groups[name] = groups
        self._markers = [
            line.strip().lower()
            for line in markers.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.hits_by_event: dict[str, list[EventHit]] = {name: [] for name in self._groups}
        self.quarantined: list[Quarantine] = []
        self.scanned: list[str] = []

    def names(self) -> list[str]:
        return sorted(self._groups)

    def defines(self, name: str) -> bool:
        return name in self._groups

    def hits(self, name: str) -> list[EventHit]:
        return self.hits_by_event.get(name, [])

    def is_quarantined(self, rel: str) -> bool:
        return any(q.source == rel for q in self.quarantined)

    # -- scanning ----------------------------------------------------------

    def scan(self, paths: list[Path], corpus_root: Path) -> None:
        for path in sorted(paths):
            rel = path.relative_to(corpus_root).as_posix()
            raw = path.read_bytes()
            marker = self._quarantine_marker(raw, rel)
            if marker is not None:
                self.quarantined.append(marker)
                continue
            self.scanned.append(rel)
            for block in _blocks(raw, rel):
                self._match(block, rel)

    def _quarantine_marker(self, raw: bytes, rel: str) -> Quarantine | None:
        text = raw.decode("utf-8", errors="replace")
        for match in COMMENT.finditer(text):
            lowered = match.group(1).lower()
            for marker in self._markers:
                if marker in lowered:
                    start = len(text[: match.start()].encode("utf-8"))
                    end = len(text[: match.end()].encode("utf-8"))
                    return Quarantine(
                        source=rel,
                        marker=marker,
                        cite=Cite(
                            path=rel,
                            byte_start=start,
                            byte_end=end,
                            snippet=match.group(0),
                            where=f"{rel}, embedded comment addressed to an automated reader",
                        ),
                    )
        return None

    def _match(self, block: Block, rel: str) -> None:
        lowered = block.text.lower()
        for name, groups in self._groups.items():
            cites: list[Cite] = []
            for group in groups:
                found = next((p for p in group if p in lowered), None)
                if found is None:
                    cites = []
                    break
                position = lowered.index(found)
                start = block.byte_start + len(block.text[:position].encode("utf-8"))
                literal = block.text[position : position + len(found)]
                cites.append(
                    Cite(
                        path=rel,
                        byte_start=start,
                        byte_end=start + len(literal.encode("utf-8")),
                        snippet=literal,
                        where=f"{rel}, phrase evidencing '{name}'",
                    )
                )
            if cites:
                self.hits_by_event[name].append(
                    EventHit(name, rel, block.text.strip(), tuple(cites))
                )


def _blocks(raw: bytes, rel: str) -> list[Block]:
    """Blank-line separated blocks, with the byte offset of each."""
    blocks: list[Block] = []
    offset = 0
    for piece in PARAGRAPH_SPLIT.split(raw):
        text = piece.decode("utf-8", errors="replace")
        if text.strip():
            blocks.append(Block(rel, offset, text))
        offset += len(piece)
        offset += 2  # the separator we split on; exact offsets are recomputed below
    # Recompute exactly: splitting loses the separator width, and a byte offset
    # that is approximately right is a citation that does not read back.
    exact: list[Block] = []
    cursor = 0
    for block in blocks:
        encoded = block.text.encode("utf-8")
        position = raw.find(encoded, cursor)
        if position < 0:  # pragma: no cover - the block came from this file
            raise ValueError(f"{rel}: could not locate a block in its own source")
        exact.append(Block(rel, position, block.text))
        cursor = position + len(encoded)
    return exact
