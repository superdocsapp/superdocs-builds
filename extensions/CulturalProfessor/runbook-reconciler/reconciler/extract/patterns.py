"""Turning passages into claims, from a rules file rather than from code.

The brief's fourth standard is configuration over code: a new rule should be a
data change, not a rewrite. So the patterns that recognise "this sentence
asserts a threshold" live in `config/claims.yaml` and this module is the engine
that runs them. Teaching the tool about a new document convention is a YAML
entry, and nobody needs to be able to write Python to do it.

## The engine, in one paragraph

A pattern has an optional `context` regex matched against the whole block — that
is what binds a value to the alert it belongs to when the two are in different
sentences — and a `pattern` regex whose named groups supply the values. Each
`emits` entry names the group whose *span* anchors the claim, so the edit
targets `800ms` and not the paragraph containing it. Subjects are templates
filled from the same groups.

`source` says what the pattern runs against: block text (the default), a code
span, a link's href, or the cells of a table row.

## Why `source: table_rows` exists

Because a DR plan puts its retention period in a table and the label that gives
it meaning is in the cell next door. A pattern over one cell's text sees
"7 days" with nothing to attach it to. Rows are reassembled from the body's
`<tr>` ranges and the blocks that fall inside them, which is possible only
because every block knows its own byte range.

## What this module is not

It is not the defence against a document that gives orders. `directive` claims
are a lexical detector and detectors can be evaded. The real defence is
structural and lives elsewhere: page text is never used as an instruction to
anything. The edit instruction sent to SuperDocs is built from a *finding* — a
subject, an observed value, an evidence path — and the passage travels as a
document to be edited, never as a prompt to be obeyed. The detector exists so a
human is told the text is there, which is what rule 3 asks for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from reconciler.claims import Anchor, Claim
from reconciler.config import CONFIG_DIR
from reconciler.extract.storage import Block, Document, occurrence_of

_ROW = re.compile(r"<tr\b[^>]*>.*?</tr>", re.DOTALL)


@dataclass(frozen=True)
class Emission:
    subject: str
    kind: str | None = None
    group: str = "0"
    value: str | None = None
    require: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class Pattern:
    id: str
    kind: str
    emits: tuple[Emission, ...]
    regex: re.Pattern[str] | None = None
    context: re.Pattern[str] | None = None
    source: str = "text"
    note: str = ""


def load_patterns(path: Path | None = None) -> list[Pattern]:
    path = path or CONFIG_DIR / "claims.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [_pattern(entry) for entry in raw.get("patterns") or []]


@lru_cache(maxsize=4)
def _cached_patterns(path_str: str) -> tuple[Pattern, ...]:
    return tuple(load_patterns(Path(path_str)))


def _compile(source: str | None) -> re.Pattern[str] | None:
    """Compile a rules-file regex in verbose mode.

    Verbose because these patterns are written across several lines in YAML, and
    a folded scalar joins those lines with a space — which would otherwise put
    literal spaces into the middle of the expression and make it match nothing.
    Every meaningful space in `config/claims.yaml` is therefore `\\s+`, which is
    also how it should have been written anyway.
    """
    return re.compile(source, re.VERBOSE) if source else None


def _pattern(entry: dict[str, Any]) -> Pattern:
    return Pattern(
        id=str(entry["id"]),
        kind=str(entry.get("kind", "resource")),
        source=str(entry.get("source", "text")),
        note=str(entry.get("note", "")),
        regex=_compile(entry.get("pattern")),
        context=_compile(entry.get("context")),
        emits=tuple(
            Emission(
                subject=str(emit["subject"]),
                kind=emit.get("kind"),
                group=str(emit.get("group", "0")),
                value=emit.get("value"),
                require=emit.get("require"),
                confidence=float(emit.get("confidence", 1.0)),
            )
            for emit in entry.get("emits") or []
        ),
    )


def extract_claims(
    document: Document, patterns: list[Pattern] | None = None, path: Path | None = None
) -> list[Claim]:
    """Every claim on one page, deduplicated by identity.

    Two patterns recognising the same sentence produce the same subject over the
    same span, which is the same `claim_id` — so the overlap costs nothing and
    patterns can be written to be readable rather than mutually exclusive.
    """
    patterns = patterns or list(_cached_patterns(str(path or CONFIG_DIR / "claims.yaml")))
    found: dict[str, Claim] = {}
    for pattern in patterns:
        for claim in _apply(pattern, document):
            found.setdefault(claim.claim_id, claim)
    return sorted(found.values(), key=lambda c: (c.anchor.char_start, c.subject))


def _apply(pattern: Pattern, document: Document) -> list[Claim]:
    if pattern.source == "table_rows":
        return _apply_to_rows(pattern, document)
    out: list[Claim] = []
    for block in document.blocks:
        if pattern.source == "links":
            out.extend(_apply_to_links(pattern, document, block))
        else:
            out.extend(_apply_to_text(pattern, document, block))
    return out


def _apply_to_text(pattern: Pattern, document: Document, block: Block) -> list[Claim]:
    if not pattern.regex or not block.text:
        return []

    bindings: dict[str, str] = {"page_id": document.page_id}
    if pattern.context:
        found = pattern.context.search(block.text)
        if not found:
            return []
        bindings.update({k: v for k, v in found.groupdict().items() if v})

    out: list[Claim] = []
    for match in pattern.regex.finditer(block.text):
        if pattern.source == "code" and not _within_code(block, match.span()):
            continue
        local = dict(bindings)
        local.update({k: v for k, v in match.groupdict().items() if v})
        out.extend(_emit(pattern, document, block, match, local))
    return out


def _apply_to_links(pattern: Pattern, document: Document, block: Block) -> list[Claim]:
    if not pattern.regex:
        return []
    out: list[Claim] = []
    for href, region in block.links:
        match = pattern.regex.search(href)
        if not match:
            continue
        bindings = {"page_id": document.page_id}
        bindings.update({k: v for k, v in match.groupdict().items() if v})
        for emit in pattern.emits:
            if emit.require and not bindings.get(emit.require):
                continue
            out.append(
                _claim(
                    document=document,
                    block=block,
                    kind=emit.kind or pattern.kind,
                    subject=emit.subject.format(**bindings),
                    asserted=href,
                    char_start=region.start,
                    char_end=region.end,
                    rule=pattern.id,
                )
            )
    return out


def _apply_to_rows(pattern: Pattern, document: Document) -> list[Claim]:
    """Label/value pairs from table rows.

    A cell knows its own bytes and a row knows which cells are in it; joining
    the two is what gives "Automated backup retention" a value to be a claim
    about.
    """
    out: list[Claim] = []
    for row in _ROW.finditer(document.body):
        cells = [
            block
            for block in document.blocks
            if block.tag in ("td", "th") and row.start() <= block.start < row.end()
        ]
        if len(cells) < 2 or cells[0].tag == "th":
            continue  # header rows label the table, they do not assert anything
        label, value = cells[0], cells[1]
        if not label.text.strip() or not value.text.strip():
            continue
        bindings = {
            "page_id": document.page_id,
            "label": _slug(label.text),
            "value": value.text.strip(),
        }
        for emit in pattern.emits:
            start, end = value.body_range(0, len(value.text))
            out.append(
                _claim(
                    document=document,
                    block=value,
                    kind=emit.kind or pattern.kind,
                    subject=emit.subject.format(**bindings),
                    asserted=value.text.strip(),
                    char_start=start,
                    char_end=end,
                    rule=pattern.id,
                    excerpt=f"{label.text.strip()}: {value.text.strip()}",
                )
            )
    return out


def _emit(
    pattern: Pattern,
    document: Document,
    block: Block,
    match: re.Match[str],
    bindings: dict[str, str],
) -> list[Claim]:
    out: list[Claim] = []
    for emit in pattern.emits:
        if emit.require and not bindings.get(emit.require):
            continue
        group = int(emit.group) if emit.group.isdigit() else emit.group
        try:
            span = match.span(group)
            captured = match.group(group)
        except (IndexError, re.error):
            # The rules file names a group this pattern does not have. That is a
            # bug in the rules file; `test_claims.py` asserts every emit's group
            # exists so it is caught there rather than silently dropping claims.
            continue
        if span == (-1, -1) or captured is None:
            continue  # an optional group that did not participate
        try:
            subject = emit.subject.format(**bindings)
        except KeyError:
            continue
        start, end = block.body_range(span[0], span[1])
        asserted = emit.value.format(**bindings) if emit.value else captured
        out.append(
            _claim(
                document=document,
                block=block,
                kind=emit.kind or pattern.kind,
                subject=subject,
                asserted=asserted,
                char_start=start,
                char_end=end,
                rule=pattern.id,
                spans_markup=block.crosses_markup(span[0], span[1]),
                value_occurrence=_value_occurrence(block.text, asserted, span[0]),
            )
        )
    return out


def _value_occurrence(text: str, asserted: str, at: int) -> int:
    """How many times this value already appeared in the block before this match.

    Counted on the same string and with the same value the apply path searches,
    so the two agree by construction rather than by both being written
    carefully. A synthesized `asserted` — one an `emits` entry supplied rather
    than captured — does not appear in the text at all and counts zero, which is
    exactly what it did before this existed.
    """
    value = asserted.strip()
    return text.count(value, 0, at) if value else 0


def _claim(
    document: Document,
    block: Block,
    kind: str,
    subject: str,
    asserted: str,
    char_start: int,
    char_end: int,
    rule: str,
    excerpt: str | None = None,
    spans_markup: bool = False,
    value_occurrence: int = 0,
) -> Claim:
    editable, refusal = block.editable, block.refusal
    if spans_markup and editable:
        # The claim is still recorded and still checked -- only the automated
        # edit is withheld. A finding a human can act on beats a silent drop.
        # A refusal the block already carries wins: "contains a status macro"
        # tells the reader more than "the value spans a tag" does.
        editable = False
        refusal = "the value is split across markup, so splicing it would rewrite a tag"
    return Claim(
        page_id=document.page_id,
        page_version=document.version,
        kind=kind,
        subject=subject,
        asserted=asserted.strip(),
        excerpt=(excerpt or block.text.strip())[:400],
        anchor=Anchor(
            heading_path=block.heading_path,
            node_index=block.index,
            content_hash=block.content_hash,
            char_start=char_start,
            char_end=char_end,
            editable=editable,
            refusal=refusal,
            occurrence=occurrence_of(document.blocks, block),
            value_occurrence=value_occurrence,
        ),
    )


def _within_code(block: Block, span: tuple[int, int]) -> bool:
    return any(start <= span[0] and span[1] <= end for start, end in block.code_spans)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


__all__ = ["Emission", "Pattern", "extract_claims", "load_patterns"]
