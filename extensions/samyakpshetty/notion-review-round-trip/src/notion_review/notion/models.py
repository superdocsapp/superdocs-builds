"""Typed Notion models — the subset of blocks the review round-trip preserves.

These mirror Notion's own JSON shapes closely enough to convert faithfully in both directions
while staying small: a block carries its rich-text runs, its type, a little type-specific
metadata (a callout's icon/colour, a code block's language), and its children.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# Block types the integration understands. Anything else round-trips as an opaque block:
# preserved on the page, shown to the reviewer as plain text, never silently dropped.
TEXTUAL_TYPES = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "toggle",
        "callout",
        "quote",
        "code",
    }
)
CONTAINER_TYPES = frozenset({"toggle", "callout", "table", "column_list", "column"})


class Annotations(BaseModel):
    model_config = {"extra": "ignore"}

    bold: bool = False
    italic: bool = False
    strikethrough: bool = False
    underline: bool = False
    code: bool = False
    color: str = "default"


class RichText(BaseModel):
    """One styled run of text — Notion flattens to ``plain_text`` + ``annotations`` + ``href``."""

    text: str
    annotations: Annotations = Field(default_factory=Annotations)
    href: str | None = None


class Block(BaseModel):
    """A Notion block. ``rich_text`` is its editable text; ``children`` its nested blocks."""

    id: str
    type: str
    rich_text: list[RichText] = Field(default_factory=list)
    children: list[Block] = Field(default_factory=list)
    has_children: bool = False
    # Type-specific metadata preserved across the round-trip (callout icon/colour, code
    # language, to_do checked, table width). Kept opaque so new fields survive untouched.
    meta: dict[str, object] = Field(default_factory=dict)

    def plain(self) -> str:
        return "".join(run.text for run in self.rich_text)


class Page(BaseModel):
    id: str
    title: str = ""
    url: str = ""


class Comment(BaseModel):
    id: str
    parent_id: str  # page id or block id the comment hangs on
    rich_text: list[RichText]
    author: str = ""  # the id of whoever wrote it — how a human reply is told from ours
    created_time: str = ""
    discussion_id: str = ""  # the thread it belongs to; replies share it

    def plain(self) -> str:
        return "".join(run.text for run in self.rich_text)


class ChildrenPage(BaseModel):
    """One page of ``GET /v1/blocks/{id}/children`` results."""

    results: list[Block] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


class DatabaseRef(BaseModel):
    """A database — its id, the URL a page can link to, and its title as Notion reports it."""

    id: str
    url: str = ""
    title: str = ""
    archived: bool = False  # Notion's search still lists a database for a while after it goes


class FileRef(BaseModel):
    """A file attached to a row — the review document going out, or the marked-up copy back.

    Notion hands back a signed URL for a file it hosts, and that URL expires, so it is fetched
    when it is read rather than stored anywhere.
    """

    name: str
    url: str


class QueueRow(BaseModel):
    """One row of an in-Notion database: a proposed change, or a request to start a review."""

    page_id: str
    status: str = ""  # the Status select the owner sets: Pending / Approved / Rejected
    url: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)  # the row as Notion returned it


def rich(text: str, **annotations: bool | str) -> RichText:
    """Build a single styled run."""
    return RichText(text=text, annotations=Annotations(**annotations))


def plain_text(text: str) -> list[RichText]:
    """Build an unstyled single-run rich-text value."""
    return [RichText(text=text)]


def row_cells(block: Block) -> list[str]:
    """A table row's cell texts, in column order.

    A ``table_row`` carries no ``rich_text``; its content lives under ``meta["cells"]`` as a
    list of runs per cell. ``Block.plain()`` is therefore empty for a row, which is why the
    write-back path reads cells rather than plain text.
    """
    cells = block.meta.get("cells")
    if not isinstance(cells, list):
        return []
    out: list[str] = []
    for cell in cells:
        if isinstance(cell, list):
            out.append("".join(str(part) for part in cell))
        else:
            out.append(str(cell))
    return out


# Notion rejects any single rich-text object whose content exceeds 2000 characters.
NOTION_RICH_TEXT_LIMIT = 2000


def _slice_runs(runs: list[RichText], start: int, end: int) -> list[RichText]:
    """Return the runs covering ``[start, end)`` in plain-text space, styling preserved."""
    out: list[RichText] = []
    pos = 0
    for run in runs:
        run_start, run_end = pos, pos + len(run.text)
        pos = run_end
        lo, hi = max(start, run_start), min(end, run_end)
        if lo < hi:
            out.append(
                RichText(
                    text=run.text[lo - run_start : hi - run_start],
                    annotations=run.annotations,
                    href=run.href,
                )
            )
    return out


def _style_at(runs: list[RichText], offset: int) -> tuple[Annotations, str | None]:
    """The annotations/link active at a plain-text offset — used to style replacement text."""
    pos = 0
    for run in runs:
        if pos <= offset < pos + len(run.text):
            return run.annotations, run.href
        pos += len(run.text)
    if runs:  # offset at or past the end inherits the trailing run's style
        return runs[-1].annotations, runs[-1].href
    return Annotations(), None


def splice_plain_edit(runs: list[RichText], new_plain: str) -> list[RichText]:
    """Apply a plain-text edit to styled runs, changing only the span that actually differs.

    The reviewer edited a passage; the rest of the block's formatting — bold, links, colour — must
    survive untouched (surgical precision). We keep the common prefix and suffix as their original
    runs and rewrite only the differing middle, styled like the text it replaces. Byte-identical
    to a plain rewrite when the block had no styling, so the simple case stays simple.
    """
    old_plain = "".join(run.text for run in runs)
    if old_plain == new_plain:
        return list(runs)

    prefix = 0
    for a, b in zip(old_plain, new_plain, strict=False):
        if a != b:
            break
        prefix += 1
    max_suffix = min(len(old_plain), len(new_plain)) - prefix
    suffix = 0
    while suffix < max_suffix and old_plain[-1 - suffix] == new_plain[-1 - suffix]:
        suffix += 1

    middle = new_plain[prefix : len(new_plain) - suffix]
    head = _slice_runs(runs, 0, prefix)
    tail = _slice_runs(runs, len(old_plain) - suffix, len(old_plain))
    if not middle:
        return [*head, *tail]
    annotations, href = _style_at(runs, prefix)
    return [*head, RichText(text=middle, annotations=annotations, href=href), *tail]


def split_rich_text(runs: list[RichText], limit: int = NOTION_RICH_TEXT_LIMIT) -> list[RichText]:
    """Split any run longer than ``limit`` into consecutive runs, preserving style and link.

    Notion caps a rich-text object's content length; a long paragraph would otherwise be rejected
    on write-back. Splitting keeps each run within the cap while the concatenated text — and every
    run's annotations and href — is byte-identical to the input.
    """
    out: list[RichText] = []
    for run in runs:
        if len(run.text) <= limit:
            out.append(run)
            continue
        for start in range(0, len(run.text), limit):
            out.append(
                RichText(
                    text=run.text[start : start + limit],
                    annotations=run.annotations,
                    href=run.href,
                )
            )
    return out


# Block references itself via ``children``; finalise the forward reference.
Block.model_rebuild()
