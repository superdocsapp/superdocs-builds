"""Cut one block in half mid-sentence, keeping both halves valid markup.

Every tag open at the cut is closed on the way out and reopened on the way in.
Offsets count text-node characters only — the same count the browser caret
reports, so the reviewer's position and this cut need no translation.

See use-cases/doc-splitter/README.md § "How it splits".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

VOID = frozenset({"br", "img", "hr", "input", "meta", "link", "col", "source", "wbr"})

_CHUNK = re.compile(r'(data-chunk-id=")([^"]*)(")')


@dataclass(frozen=True, slots=True)
class Cut:
    """Where a new part begins. `offset` counts text-node characters; 0 is the
    block's start (a marker dropped on a heading)."""

    chunk_id: str
    offset: int = 0


def text_length(html: str) -> int:
    """How many characters a cut offset may address in this block."""
    return len(_Splitter(0).run(html)[2])


class _Splitter(HTMLParser):
    """One pass: everything before the offset, everything after, and the text."""

    def __init__(self, offset: int) -> None:
        super().__init__(convert_charrefs=False)
        # Not `self.offset`: HTMLParser (via ParserBase) uses that name for
        # line/column tracking and rewrites it every token, so a cut stored there
        # silently lands at the end of the block. Hence `_cut`.
        self._cut = offset
        self.before: list[str] = []
        self.after: list[str] = []
        self.text: list[str] = []
        self._seen = 0
        self.open: list[str] = []
        """Tags open at the cursor — closed in reverse out, reopened in order in."""
        self.opened_html: list[str] = []
        self._done = False

    # ── output ───────────────────────────────────────────────────────────
    def _emit(self, markup: str) -> None:
        (self.after if self._done else self.before).append(markup)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        markup = self.get_starttag_text() or ""
        self._emit(markup)
        if tag not in VOID:
            self.open.append(tag)
            self.opened_html.append(markup)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._emit(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.open:
            index = len(self.open) - 1 - self.open[::-1].index(tag)
            self.open.pop(index)
            self.opened_html.pop(index)
        self._emit(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._done:
            self.after.append(data)
            return
        remaining = self._cut - self._seen
        if self._seen + len(data) <= self._cut:
            self.before.append(data)
            self._seen += len(data)
            return
        # The cut lands inside this run of text.
        self.before.append(data[:remaining])
        self._close_and_reopen()
        self.after.append(data[remaining:])
        self._seen = self._cut

    def _emit_entity(self, markup: str, size: int = 1) -> None:
        self.text.append(markup)
        if self._done or self._seen + size <= self._cut:
            self._emit(markup)
            if not self._done:
                self._seen += size
            return
        self._close_and_reopen()
        self.after.append(markup)

    def handle_entityref(self, name: str) -> None:
        self._emit_entity(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._emit_entity(f"&#{name};")

    def _close_and_reopen(self) -> None:
        """Close every open tag into `before`, queue them to reopen in `after`."""
        for tag in reversed(self.open):
            self.before.append(f"</{tag}>")
        self.after.extend(self.opened_html)
        self._done = True

    def run(self, html: str) -> tuple[str, str, str]:
        self.feed(html)
        self.close()
        if not self._done:
            # Offset at/past the end: everything is "before", second half empty.
            self._close_and_reopen()
            self.after = []
        return "".join(self.before), "".join(self.after), "".join(self.text)


def split_html(html: str, offset: int) -> tuple[str, str]:
    """`(before, after)` — both valid markup, together holding every character.
    `offset <= 0` puts everything in `after`; at/past the end, everything in
    `before`."""
    if offset <= 0:
        return "", html
    before, after, text = _Splitter(offset).run(html)
    if offset >= len(text):
        return html, ""
    return before, after


def relabel(html: str, suffix: str) -> str:
    """Give a half its own chunk id (`x#a`, `x#b`), so the coverage check does
    not read two halves of one block as a duplicate id."""
    return _CHUNK.sub(lambda m: f"{m.group(1)}{m.group(2)}{suffix}{m.group(3)}", html, count=1)
