"""Convert a Notion block tree to HTML for SuperDocs, recording a reversible block map.

Each editable block is rendered as one leaf-level element carrying ``data-nr-id`` (the Notion
block id) so we can find it again after the round-trip, and ``data-nr-type`` (the Notion block
type) so we can write the change back to the right kind of block. Structural containers — a
toggle's ``details``, a callout's ``aside``, a table — wrap their children without a marker, so
only genuinely editable text is ever mapped to a chunk. Rich-text styling (bold, italic, links,
code) is preserved so the reviewer's Word copy reads naturally.

The returned :class:`~notion_review.domain.BlockMapEntry` list is the spine of the round-trip:
it ties every Notion block to the chunk SuperDocs will assign, so an approved change lands on
exactly the block it came from.
"""

from __future__ import annotations

from html import escape

from notion_review.domain import BlockMapEntry
from notion_review.notion.models import Block, RichText

_HEADINGS = {"heading_1": "h1", "heading_2": "h2", "heading_3": "h3"}


def render_rich_text(runs: list[RichText]) -> str:
    """Render Notion rich-text runs to inline HTML, preserving styling and links."""
    out: list[str] = []
    for run in runs:
        text = escape(run.text)
        ann = run.annotations
        if ann.code:
            text = f"<code>{text}</code>"
        if ann.bold:
            text = f"<strong>{text}</strong>"
        if ann.italic:
            text = f"<em>{text}</em>"
        if ann.strikethrough:
            text = f"<s>{text}</s>"
        if ann.underline:
            text = f"<u>{text}</u>"
        if run.href:
            text = f'<a href="{escape(run.href, quote=True)}">{text}</a>'
        out.append(text)
    return "".join(out)


def blocks_to_html(blocks: list[Block]) -> tuple[str, list[BlockMapEntry]]:
    """Render top-level blocks to HTML and collect the block map (parents before children)."""
    block_map: list[BlockMapEntry] = []
    html = "".join(_render(block, block_map) for block in blocks)
    return html, block_map


def _leaf(
    tag: str, block: Block, inner: str, block_map: list[BlockMapEntry], extra: str = ""
) -> str:
    """Render one editable block as a marked leaf element and record its map entry."""
    element = f'<{tag} data-nr-id="{block.id}" data-nr-type="{block.type}"{extra}>{inner}</{tag}>'
    block_map.append(
        BlockMapEntry(
            notion_block_id=block.id,
            block_type=block.type,
            anchor=block.id,
            original_html=element,
            original_text=block.plain(),
        )
    )
    return element


def _children_html(block: Block, block_map: list[BlockMapEntry]) -> str:
    return "".join(_render(child, block_map) for child in block.children)


def _render(block: Block, block_map: list[BlockMapEntry]) -> str:
    t = block.type
    inner = render_rich_text(block.rich_text)

    if t in _HEADINGS:
        return _leaf(_HEADINGS[t], block, inner, block_map)
    if t == "paragraph":
        return _leaf("p", block, inner, block_map) + _children_html(block, block_map)
    if t == "quote":
        return _leaf("blockquote", block, inner, block_map)
    if t == "to_do":
        mark = "☑ " if block.meta.get("checked") else "☐ "
        return _leaf("p", block, mark + inner, block_map)
    if t == "bulleted_list_item":
        return f"<ul>{_leaf('li', block, inner, block_map)}</ul>" + _children_html(block, block_map)
    if t == "numbered_list_item":
        return f"<ol>{_leaf('li', block, inner, block_map)}</ol>" + _children_html(block, block_map)
    if t == "code":
        lang = escape(str(block.meta.get("language", "")), quote=True)
        return _leaf(
            "pre", block, escape(block.plain()), block_map, extra=f' data-nr-language="{lang}"'
        )
    if t == "toggle":
        # The title is a <p> *inside* the <summary>, not the <summary> itself. Measured on the
        # live service, 27 Aug 2026: a bare <summary> is dropped on upload — its text reaches
        # no chunk at all, so a reviewer's edit to a toggle title had nowhere to land. Wrapped
        # in a <p> it chunks like any other paragraph and round-trips. This was our HTML, not
        # their parser.
        title = _leaf("p", block, inner, block_map)
        return (
            f'<details data-nr-type="toggle"><summary>{title}</summary>'
            f"{_children_html(block, block_map)}</details>"
        )
    if t == "callout":
        icon = escape(str(block.meta.get("icon", "")), quote=True)
        color = escape(str(block.meta.get("color", "default")), quote=True)
        body = _leaf("p", block, inner, block_map)
        wrap = f'<aside class="callout" data-nr-icon="{icon}" data-nr-color="{color}">'
        return f"{wrap}{body}{_children_html(block, block_map)}</aside>"
    if t == "table":
        # One <table> per row, deliberately, rather than one table holding every row. Measured
        # on the live service: a multi-row table is re-chunked as a single unit, so all four
        # rows of a pricing table shared one chunk id and no individual row could be addressed
        # — an approved edit to one cell would have rewritten the whole table. One row per
        # table gives each row its own chunk. It still reads as a table for the reviewer.
        return "".join(_render_row(row, block_map) for row in block.children)
    if t == "child_database":
        title = escape(str(block.meta.get("title", "Inline database")))
        # Preserved, not editable as text — no map entry, so it can never be changed by a review.
        return f'<aside class="inline-db" data-nr-type="child_database">\U0001f4ca {title}</aside>'
    if t == "divider":
        return "<hr>"

    # Unknown block: preserve it, and map it only if it carries text a reviewer could edit.
    #
    # Notion reports anything its API does not model — a button, an embed, a synced block — as
    # ``unsupported`` with no rich text. Mapping one would put an entry with empty text in the
    # block map, where it competes to match any empty paragraph in the returned document and
    # could win a change that would then be written to a block holding no text. The button that
    # starts a review lives on the very page being reviewed, so this is the common case, not an
    # exotic one. Preserved in the document, absent from the map: the same call as an inline
    # database.
    if not block.plain().strip():
        return f'<div data-nr-type="{escape(block.type, quote=True)}"></div>'
    return _leaf("div", block, inner or escape(block.plain()), block_map)


def _render_row(row: Block, block_map: list[BlockMapEntry]) -> str:
    cells = row.meta.get("cells", [])
    tds: list[str] = []
    texts: list[str] = []
    if isinstance(cells, list):
        for cell in cells:
            value = "".join(str(part) for part in cell) if isinstance(cell, list) else str(cell)
            texts.append(value)
            tds.append(f"<td>{escape(value)}</td>")
    # The single space between cells is load-bearing: chunks are matched back by text, and
    # `<td>a</td><td>b</td>` reads as "ab" once the tags are gone, which matches nothing.
    # A space between the cells survives the upload and reads as "a b". Measured.
    element = (
        f'<table data-nr-type="table">'
        f'<tr data-nr-id="{row.id}" data-nr-type="table_row">{" ".join(tds)}</tr>'
        f"</table>"
    )
    block_map.append(
        BlockMapEntry(
            notion_block_id=row.id,
            block_type="table_row",
            anchor=row.id,
            original_html=element,
            original_text=" ".join(texts),
            cells=list(texts),
        )
    )
    return element
