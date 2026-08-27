"""Reading a report format, and binding an inspection into it.

A report format is a **Word document**. Not HTML with markers in it — a `.docx` a firm opens
in Word, edits, and recognises as their report. That is the whole point: this build exists
because inspection reports are not written for the person reading them, and a format nobody
can open is a format nobody will redesign.

The markers are therefore things a person types in Word. A token is square-bracketed text:

    [firm name]  [property address]  [inspector]  [date of inspection]
    [systems inspected]  [system summary]  [findings]
    [severity label]  [location]  [observation]  [recommendation]
    [photograph]  [caption]

They survive the round trip through SuperDocs intact, which is the reason for this design
rather than the previous one: upload parses a document into chunks and **drops HTML
comments**, so a format marked up with ``<!-- region:system -->`` could not come back from
the service with the markers the binder needed. Bracketed text is not markup. It survives,
and it reads as an instruction to a human author, which a comment never did.

Two things are found by shape rather than by name, so the format stays a document instead of
becoming a configuration file:

* **The worked example.** A format shows how one finding is recorded — the severity label and
  location, what was observed, the recommended next step, the photograph and its caption. The
  binder reads that example *as the per-finding template*, then removes the whole section
  from the finished report. So a firm changes the layout of every finding by editing one
  example in Word.
* **The photograph pair inside it.** Whichever blocks of the example carry ``[photograph]``
  and ``[caption]`` are the part repeated once per photograph.

Binding stays strict. A token nobody filled is an error naming it, never a gap in a document
a buyer will read. The one thing that is never an error is a system with no findings — that
is a real and important outcome, and it renders as the sentence saying so.

Structure never passes through a model. Which system a finding appears under, and in what
order, is decided by the caller from the catalogue, and spliced in here.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

# SuperDocs returns a flat sequence of block elements — one per chunk — with lists kept whole
# as a single <ul>. Verified against what the service actually returns for a .docx upload.
_BLOCK = re.compile(
    r"<(?P<tag>h[1-6]|p|ul|ol|table|blockquote)\b(?P<attrs>[^>]*)>(?P<inner>.*?)</(?P=tag)\s*>",
    re.DOTALL | re.IGNORECASE,
)
# Deliberately narrow: no newlines, no nesting, short. Ordinary prose in a report does not
# match this, and a format that wants a literal bracket writes it outside a single line.
_TOKEN = re.compile(r"\[([a-z][a-z ]{0,38})\]", re.IGNORECASE)

DOCUMENT_TOKENS = frozenset(
    {"firm name", "property address", "inspector", "date of inspection", "systems inspected"}
)
SYSTEM_TOKENS = frozenset({"findings", "system summary"})
FINDING_TOKENS = frozenset({"severity label", "location", "observation", "recommendation"})
PHOTO_TOKENS = frozenset({"photograph", "caption"})
EVERY_TOKEN = DOCUMENT_TOKENS | SYSTEM_TOKENS | FINDING_TOKENS | PHOTO_TOKENS


class TemplateError(Exception):
    """A format could not be read or bound. The message names the cause and the fix."""


@dataclass(frozen=True)
class Block:
    """One top-level element of the format, exactly as it arrived."""

    raw: str
    tag: str
    text: str

    @property
    def is_heading(self) -> bool:
        return self.tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}


def parse_blocks(html: str) -> list[Block]:
    out: list[Block] = []
    for m in _BLOCK.finditer(html):
        inner = m.group("inner")
        text = html_lib.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        out.append(Block(raw=m.group(0), tag=m.group("tag").lower(), text=" ".join(text.split())))
    return out


def normalise(name: str) -> str:
    return " ".join(name.split()).lower()


def tokens_in(fragment: str) -> set[str]:
    """Every recognised token in a fragment, normalised."""
    return {normalise(m.group(1)) for m in _TOKEN.finditer(fragment)} & EVERY_TOKEN


def unknown_tokens_in(fragment: str) -> set[str]:
    """Bracketed text that looks like a token but is not one — almost always a typo."""
    return {normalise(m.group(1)) for m in _TOKEN.finditer(fragment)} - EVERY_TOKEN


def fill(fragment: str, values: dict[str, str]) -> str:
    """Substitute the tokens this caller knows about, leaving the rest for a later pass."""

    def swap(match: re.Match[str]) -> str:
        key = normalise(match.group(1))
        return values[key] if key in values else match.group(0)

    return _TOKEN.sub(swap, fragment)


# The class the AI rewrite pass targets. Stamped by the binder onto whichever paragraph the
# format uses for the observation, so a firm authoring a format in Word never has to know it
# exists. `class` survives upload where `data-*` attributes and HTML comments do not — that
# was measured against the live service, and it is why the marker is a class.
NOTE_CLASS = "finding-note"

_OPEN_TAG = re.compile(r"<(?P<tag>[a-z][a-z0-9]*)(?P<attrs>[^>]*)>", re.IGNORECASE)


def stamp_class(raw: str, name: str) -> str:
    """Add a class to a block's outermost tag, keeping any classes already there."""
    match = _OPEN_TAG.search(raw)
    if match is None:
        return raw
    attrs = match.group("attrs")
    existing = re.search(r'class="([^"]*)"', attrs, re.IGNORECASE)
    if existing is None:
        new_attrs = f'{attrs} class="{name}"'
    elif name in existing.group(1).split():
        return raw
    else:
        new_attrs = attrs.replace(existing.group(0), f'class="{existing.group(1)} {name}"', 1)
    opened = f"<{match.group('tag')}{new_attrs}>"
    return raw[: match.start()] + opened + raw[match.end() :]


@dataclass(frozen=True)
class FindingShape:
    """How this format records one finding, read from its own worked example."""

    before: tuple[str, ...]
    photo: tuple[str, ...]
    after: tuple[str, ...]

    @property
    def carries_photos(self) -> bool:
        return bool(self.photo)


@dataclass(frozen=True)
class ReportFormat:
    """A format, read once and ready to bind."""

    blocks: tuple[Block, ...]
    finding_shape: FindingShape
    # The worked-example section, as a half-open range of block indices. It is scaffolding
    # for whoever authors the format, and it is removed from every finished report.
    example_span: tuple[int, int]
    # System heading text -> index of the block in that section carrying [findings].
    system_slots: dict[str, int]
    # System heading text -> index of the block carrying [system summary], where one exists.
    summary_slots: dict[str, int]


def read_format(html: str, system_names: list[str]) -> ReportFormat:
    """Read a format's shape, refusing anything a report cannot be built from.

    ``system_names`` comes from the catalogue, so a format is held to the systems this build
    actually reports on rather than to whatever headings it happens to contain.
    """
    blocks = parse_blocks(html)
    if not blocks:
        raise TemplateError(
            "this format has no content the binder can read. It should be a Word document "
            "with headings and paragraphs."
        )

    stray = set().union(*(unknown_tokens_in(b.raw) for b in blocks)) if blocks else set()
    if stray:
        raise TemplateError(
            f"this format uses bracketed text that is not a token: {sorted(stray)}. "
            f"The tokens this build fills are {sorted(EVERY_TOKEN)}. Fix the wording in "
            f"Word, or remove the brackets if it is meant to be read as prose."
        )

    shape, span = _read_worked_example(blocks)
    system_slots, summary_slots = _read_system_sections(blocks, system_names, span)
    return ReportFormat(
        blocks=tuple(blocks),
        finding_shape=shape,
        example_span=span,
        system_slots=system_slots,
        summary_slots=summary_slots,
    )


def _read_worked_example(blocks: list[Block]) -> tuple[FindingShape, tuple[int, int]]:
    """Find the example that shows how one finding is recorded, and the section holding it."""
    carrying = [
        i for i, b in enumerate(blocks) if tokens_in(b.raw) & (FINDING_TOKENS | PHOTO_TOKENS)
    ]
    if not carrying:
        raise TemplateError(
            "this format never shows how a finding is recorded, so there is nothing to "
            "repeat per finding. Add a short worked example using "
            f"{sorted(FINDING_TOKENS)} — and {sorted(PHOTO_TOKENS)} if the format carries "
            "photographs."
        )
    first, last = carrying[0], carrying[-1]
    gaps = [i for i in range(first, last + 1) if i not in carrying]
    if gaps:
        raise TemplateError(
            f"the worked example is interrupted at block {gaps[0]} "
            f"({blocks[gaps[0]].text[:48]!r}). Keep the example's paragraphs together, so "
            f"the binder repeats the finding and nothing else."
        )

    photo_idx = [i for i in carrying if tokens_in(blocks[i].raw) & PHOTO_TOKENS]
    if photo_idx and photo_idx != list(range(photo_idx[0], photo_idx[-1] + 1)):
        raise TemplateError(
            "the photograph and caption paragraphs are not next to each other. They are "
            "repeated once per photograph, so they have to be a single run."
        )
    p_start = photo_idx[0] if photo_idx else last + 1
    p_end = photo_idx[-1] + 1 if photo_idx else last + 1

    def block_html(i: int) -> str:
        # The observation paragraph is what the AI rewrite pass is pointed at, so it is
        # marked here rather than in the Word document. A format author writes [observation];
        # the class is this build's business, not theirs.
        raw = blocks[i].raw
        return stamp_class(raw, NOTE_CLASS) if "observation" in tokens_in(raw) else raw

    shape = FindingShape(
        before=tuple(block_html(i) for i in range(first, p_start)),
        photo=tuple(block_html(i) for i in range(p_start, p_end)),
        after=tuple(block_html(i) for i in range(p_end, last + 1)),
    )

    # The example is scaffolding, so the whole section goes: back to the heading above it,
    # forward to the next heading.
    start = first
    while start > 0 and not blocks[start - 1].is_heading:
        start -= 1
    if start > 0:
        start -= 1  # the heading itself
    end = last + 1
    while end < len(blocks) and not blocks[end].is_heading:
        end += 1
    return shape, (start, end)


def _read_system_sections(
    blocks: list[Block], system_names: list[str], example_span: tuple[int, int]
) -> tuple[dict[str, int], dict[str, int]]:
    """Locate each system's heading and the slot its findings go into."""
    wanted = {normalise(n): n for n in system_names}
    heading_at: dict[str, int] = {}
    for i, block in enumerate(blocks):
        if example_span[0] <= i < example_span[1] or not block.is_heading:
            continue
        key = normalise(block.text)
        if key in wanted and wanted[key] not in heading_at:
            heading_at[wanted[key]] = i

    missing = [n for n in system_names if n not in heading_at]
    if missing:
        raise TemplateError(
            f"this format has no heading for {missing}. Every inspection system in the "
            f"catalogue needs a section of its own — a system with nothing under it still "
            f"has to say so, because silence about a system reads as 'not inspected'."
        )

    slots: dict[str, int] = {}
    summaries: dict[str, int] = {}
    for name, at in heading_at.items():
        end = at + 1
        while end < len(blocks) and not blocks[end].is_heading:
            end += 1
        for i in range(at + 1, end):
            found = tokens_in(blocks[i].raw)
            if "findings" in found and name not in slots:
                slots[name] = i
            if "system summary" in found and name not in summaries:
                summaries[name] = i
        if name not in slots:
            raise TemplateError(
                f"the {name!r} section has nowhere to put its findings. Add a paragraph "
                f"reading [findings] under that heading."
            )
    return slots, summaries


def carries_photos(html: str, system_names: list[str]) -> bool:
    """Whether this format has anywhere to put a photograph.

    A format decides what it carries: the repair-priority list has no photograph in its
    worked example on purpose, and the export verifier reads this rather than holding every
    format to the same promise. A format that cannot be read at all answers ``False``,
    because a report was never built from it in the first place.
    """
    try:
        return read_format(html, system_names).finding_shape.carries_photos
    except TemplateError:
        return False


def render_finding(
    shape: FindingShape, values: dict[str, str], photos: list[dict[str, str]]
) -> str:
    """One finding, in the format's own shape, with its photograph run repeated per photo."""
    parts = [fill(raw, values) for raw in shape.before]
    for photo in photos:
        parts.extend(fill(raw, {**values, **photo}) for raw in shape.photo)
    parts.extend(fill(raw, values) for raw in shape.after)
    return "".join(parts)


def assemble(
    fmt: ReportFormat,
    *,
    document: dict[str, str],
    system_findings: dict[str, str],
    system_nothing: dict[str, str],
    system_summaries: dict[str, str],
) -> str:
    """Put the report together: example section removed, slots filled, everything else kept.

    ``system_findings`` maps a system's heading text to the rendered HTML for its findings.
    Where that is empty, the format's own paragraph is kept and ``system_nothing`` goes
    inside it — so a system with nothing under it still says so, in the same shape as the
    rest of the report. Silence about a system reads as "not inspected", which is a
    different and more dangerous claim.
    """
    out: list[str] = []
    for i, block in enumerate(fmt.blocks):
        if fmt.example_span[0] <= i < fmt.example_span[1]:
            continue
        raw = block.raw
        for name, at in fmt.summary_slots.items():
            if at == i:
                raw = fill(raw, {"system summary": system_summaries.get(name, "")})
        slot_for = next((n for n, at in fmt.system_slots.items() if at == i), None)
        if slot_for is not None:
            rendered = system_findings.get(slot_for, "")
            out.append(
                rendered
                if rendered
                else fill(raw, {**document, "findings": system_nothing.get(slot_for, "")})
            )
            continue
        out.append(fill(raw, document))

    html = "\n".join(out)
    left = tokens_in(html)
    if left:
        raise TemplateError(
            f"nothing was supplied for {sorted(left)}, so the report would go to a buyer "
            f"with a gap where a fact belongs. Either supply the value or remove the token "
            f"from the format."
        )
    return html
