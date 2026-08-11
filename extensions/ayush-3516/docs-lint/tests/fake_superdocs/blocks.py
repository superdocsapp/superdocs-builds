"""Markdown <-> chunked HTML, the way the fake service models a document.

The fake keeps documents as an ordered list of Markdown blocks, each with a stable chunk id, and
renders HTML from that. Export re-joins the Markdown blocks.

That round-trip is exact by construction, which is the point: it lets a test assert that a block
nobody approved a change for comes back byte-identical. If the fake round-tripped only
approximately, "nothing else changed" would be untestable here.
"""

from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Block:
    """One addressable region of a document."""

    chunk_id: str
    text: str
    kind: str = "paragraph"

    def to_html(self) -> str:
        escaped = html.escape(self.text)
        if self.kind == "heading":
            match = HEADING.match(self.text)
            level = len(match.group(1)) if match else 1
            inner = html.escape(match.group(2)) if match else escaped
            return f'<h{level} data-chunk-id="{self.chunk_id}">{inner}</h{level}>'
        if self.kind == "code":
            return f'<pre data-chunk-id="{self.chunk_id}"><code>{escaped}</code></pre>'
        return f'<p data-chunk-id="{self.chunk_id}">{escaped}</p>'


def split_blocks(markdown: str) -> list[Block]:
    """Split Markdown into blocks on blank lines, keeping fenced code together.

    Blank-line separation is a simplification of Markdown's real block grammar, and that is fine:
    this is the fake service's internal model, not the linter's parser. The linter uses
    markdown-it-py. What matters here is that the split is stable and reversible.
    """
    blocks: list[Block] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = "\n".join(current).strip("\n")
        if text.strip():
            # UUIDs, matching the live service. Sequential ids would let a test accidentally
            # depend on guessable chunk names, which the real API would never give it.
            blocks.append(Block(str(uuid.uuid4()), text, _kind_of(text)))
        current = []

    for line in markdown.splitlines():
        if FENCE.match(line):
            current.append(line)
            if in_fence:
                in_fence = False
                flush()
            else:
                in_fence = True
            continue
        if in_fence:
            current.append(line)
            continue
        if not line.strip():
            flush()
            continue
        current.append(line)
    flush()
    return blocks


def _kind_of(text: str) -> str:
    if FENCE.match(text):
        return "code"
    if HEADING.match(text):
        return "heading"
    return "paragraph"


def render_html(blocks: list[Block]) -> str:
    return "\n".join(block.to_html() for block in blocks)


def render_markdown(blocks: list[Block]) -> str:
    """Re-join blocks into a Markdown document, blank line separated, trailing newline."""
    return "\n\n".join(block.text for block in blocks) + "\n"
