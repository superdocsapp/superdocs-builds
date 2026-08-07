"""Independent, section-level proof of what changed in a document.

The API tells us which sections it edited. That is an assertion. This
module is the proof: it re-derives the answer from the document bytes
themselves and, when the two disagree, the bytes win and the run is
flagged.

SuperDocs marks every editable section with ``data-chunk-id``. We build
``{chunk_id: outer_html}`` for two versions of a document and compare. A
chunk that is not in the intended set must be **byte-identical**, or the
edit was not surgical.

Implementation note (this is the fiddly part): we need the *outer* HTML of
each chunk element, including nesting - a table row carries a chunk id and
so does the table around it. ``html.parser`` gives us positions, not
slices, so we convert its (line, col) into absolute offsets ourselves and
cut the original string. That keeps the comparison byte-exact instead of
round-tripping through a serialiser that would normalise away the very
differences we are trying to detect.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}


class _ChunkParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self._line_starts = [0]
        for i, ch in enumerate(source):
            if ch == "\n":
                self._line_starts.append(i + 1)
        self.chunks: dict[str, str] = {}
        self.order: list[str] = []
        self._stack: list[tuple[str, str | None, int]] = []  # tag, chunk_id, start_offset

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        chunk_id = dict(attrs).get("data-chunk-id")
        if tag in VOID_TAGS:
            if chunk_id:
                start = self._offset()
                end = self.source.find(">", start)
                self._store(chunk_id, self.source[start: end + 1 if end != -1 else len(self.source)])
            return
        self._stack.append((tag, chunk_id, self._offset()))

    def handle_startendtag(self, tag, attrs):
        chunk_id = dict(attrs).get("data-chunk-id")
        if chunk_id:
            start = self._offset()
            end = self.source.find(">", start)
            self._store(chunk_id, self.source[start: end + 1 if end != -1 else len(self.source)])

    def handle_endtag(self, tag):
        end_open = self._offset()
        close = self.source.find(">", end_open)
        end = close + 1 if close != -1 else len(self.source)
        # Pop to the matching open tag, tolerating unclosed inline elements.
        for idx in range(len(self._stack) - 1, -1, -1):
            if self._stack[idx][0] == tag:
                for _ in range(len(self._stack) - idx):
                    open_tag, chunk_id, start = self._stack.pop()
                    if chunk_id:
                        self._store(chunk_id, self.source[start:end])
                return

    def _store(self, chunk_id: str, html: str) -> None:
        if chunk_id not in self.chunks:
            self.order.append(chunk_id)
        self.chunks[chunk_id] = html


def chunk_map(html: str) -> dict[str, str]:
    """{chunk_id -> exact outer HTML}. Empty dict if the document carries no
    chunk ids (which is itself a useful signal, not a crash)."""
    if not html:
        return {}
    parser = _ChunkParser(html)
    parser.feed(html)
    parser.close()
    return parser.chunks


def chunk_order(html: str) -> list[str]:
    parser = _ChunkParser(html)
    parser.feed(html)
    parser.close()
    return parser.order


_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")


def visible_text(html: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", html or "")).strip()


def residue_map(html: str) -> dict[str, str]:
    """{chunk_id -> the chunk's OWN bytes, with nested chunks blanked out}.

    Why this exists: chunk ids nest. A table carries one, its rows carry
    theirs, its cells theirs again. Edit a single cell and a naive byte
    comparison reports three "changed" sections - cell, row, table - and the
    surgical-precision check drowns in false positives.

    Blanking each descendant chunk down to a placeholder leaves only the
    bytes a chunk owns directly. A table whose cell changed now has an
    unchanged residue (correctly: the table itself did not change), while a
    table whose *border* changed still has a changed residue (correctly: that
    edit was independent of the cell). No special cases, no heuristics about
    tag names - it falls out of the containment structure itself.
    """
    chunks = chunk_map(html)
    out: dict[str, str] = {}
    # Longest first so a nested replacement never eats a shorter sibling.
    ordered = sorted(chunks.items(), key=lambda kv: len(kv[1]), reverse=True)
    for cid, own in chunks.items():
        residue = own
        for other_id, other_html in ordered:
            if other_id == cid or len(other_html) >= len(own):
                continue
            if other_html in residue:
                residue = residue.replace(other_html, f"\x00{other_id}\x00")
        out[cid] = residue
    return out


@dataclass
class SectionDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def touched(self) -> set[str]:
        return set(self.added) | set(self.removed) | set(self.modified)

    def as_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "modified": self.modified,
            "unchanged_count": len(self.unchanged),
        }


def diff_chunks(before_html: str, after_html: str, *, own_bytes_only: bool = True) -> SectionDiff:
    """Section-level diff between two versions of the same document.

    ``own_bytes_only=True`` (default) compares each chunk's own bytes, so a
    container is only "modified" when the container itself changed - see
    ``residue_map``. Set it False for raw outer-HTML comparison.
    """
    if own_bytes_only:
        before, after = residue_map(before_html), residue_map(after_html)
    else:
        before, after = chunk_map(before_html), chunk_map(after_html)
    out = SectionDiff()
    for cid, html in after.items():
        if cid not in before:
            out.added.append(cid)
        elif before[cid] != html:
            out.modified.append(cid)
        else:
            out.unchanged.append(cid)
    out.removed = [cid for cid in before if cid not in after]
    out.added.sort(); out.modified.sort(); out.removed.sort()
    return out


_TAG_NAME = re.compile(r"^<\s*([a-zA-Z0-9]+)")


def top_level_chunks(html: str) -> list[str]:
    """Chunk ids that are not nested inside another chunk, in document order."""
    chunks = chunk_map(html)
    order = chunk_order(html)
    tops = []
    for cid in order:
        own = chunks[cid]
        if not any(cid != other and own in html_other for other, html_other in chunks.items()):
            tops.append(cid)
    return tops


@dataclass
class Section:
    """A heading and everything under it, up to the next heading of the same
    or higher level. This is what a human means by "the What is at risk
    section" - the API thinks in chunks, readers think in sections."""

    heading: str
    level: int
    heading_chunk: str
    chunk_ids: list[str] = field(default_factory=list)

    @property
    def body_chunk_ids(self) -> list[str]:
        return [c for c in self.chunk_ids if c != self.heading_chunk]


def sections(html: str) -> list[Section]:
    chunks = chunk_map(html)
    result: list[Section] = []
    current: Section | None = None
    for cid in top_level_chunks(html):
        m = _TAG_NAME.match(chunks[cid].lstrip())
        tag = (m.group(1).lower() if m else "")
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            level = int(tag[1])
            while result and current and current.level >= level and current is not result[-1]:
                break
            current = Section(visible_text(chunks[cid]), level, cid, [cid])
            result.append(current)
        elif current is not None:
            current.chunk_ids.append(cid)
    # descendants of each top-level chunk belong to the same section
    for sec in result:
        expanded: list[str] = []
        for cid in sec.chunk_ids:
            expanded.append(cid)
            own = chunks[cid]
            expanded.extend(
                other for other, oh in chunks.items() if other != cid and oh in own
            )
        seen: set[str] = set()
        sec.chunk_ids = [c for c in expanded if not (c in seen or seen.add(c))]
    return result


def section_named(html: str, name: str) -> Section | None:
    needle = name.strip().lower()
    best = None
    for sec in sections(html):
        head = sec.heading.strip().lower()
        if head == needle:
            return sec
        if needle in head and best is None:
            best = sec
    return best


_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.S | re.I)


def _section_html_no_chunks(html: str, name: str) -> str:
    """Fallback for HTML that carries no chunk ids - an exported file, a
    hand-written fixture, or anything that did not come from a chat turn.
    Chunk-level precision is impossible here, but section slicing is not, so
    the caller degrades to a coarser answer instead of getting nothing."""
    needle = name.strip().lower()
    matches = list(_HEADING_RE.finditer(html or ""))
    for i, m in enumerate(matches):
        if visible_text(m.group(2)).strip().lower() != needle:
            continue
        level = int(m.group(1))
        end = len(html)
        for later in matches[i + 1:]:
            if int(later.group(1)) <= level:
                end = later.start()
                break
        return html[m.start():end]
    return ""


def section_html(html: str, name: str) -> str:
    """The raw bytes of one section: its heading plus everything until the next
    heading of the same or higher level."""
    secs = sections(html)
    chunks = chunk_map(html)
    if not chunks:
        return _section_html_no_chunks(html, name)
    for i, sec in enumerate(secs):
        if sec.heading.strip().lower() != name.strip().lower():
            continue
        start = html.find(chunks[sec.heading_chunk])
        end = len(html)
        for later in secs[i + 1:]:
            if later.level <= sec.level:
                pos = html.find(chunks[later.heading_chunk])
                if pos > start:
                    end = pos
                break
        return html[start:end]
    return ""


def table_rows(html_fragment: str) -> list[list[str]]:
    """Every <tr> in a fragment as a list of cell texts. Deliberately naive -
    it is used to check content, and the byte-level checks live elsewhere."""
    rows = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_fragment or "", re.S | re.I):
        cells = [
            visible_text(c) for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        ]
        if cells:
            rows.append(cells)
    return rows


def list_items(html_fragment: str) -> list[str]:
    return [
        visible_text(li)
        for li in re.findall(r"<li\b[^>]*>(.*?)</li>", html_fragment or "", re.S | re.I)
    ]


def chunks_of_sections(html: str, names: list[str]) -> set[str]:
    out: set[str] = set()
    for name in names:
        sec = section_named(html, name)
        if sec:
            out |= set(sec.chunk_ids)
    return out


@dataclass
class SurgeryVerdict:
    """Did this edit change ONLY what it was supposed to?"""

    ok: bool
    intended: list[str]
    unintended: list[str]
    missing: list[str]
    unchanged_count: int
    detail: dict = field(default_factory=dict)

    def render(self) -> str:
        head = "PASS" if self.ok else "FAIL"
        return (
            f"[{head}] intended={len(self.intended)} unintended={len(self.unintended)} "
            f"missing={len(self.missing)} byte-identical={self.unchanged_count}"
            + ("" if self.ok else f"\n  unintended: {self.unintended}\n  missing: {self.missing}")
        )


def verify_surgical(
    before_html: str,
    after_html: str,
    *,
    expected_chunk_ids: set[str] | None = None,
    expected_sections: list[str] | None = None,
    expected_text: list[str] | None = None,
    allow_new: bool = True,
    require_all: bool = False,
) -> SurgeryVerdict:
    """Compare two document versions against an intent.

    ``expected_chunk_ids`` - the sections we meant to touch.
    ``expected_sections``  - heading names; every chunk under those headings
                             (in the BEFORE document) counts as intended.
    ``expected_text``      - markers matched against a chunk's OWN bytes, so a
                             wrapping table never absorbs its cell's intent.
    ``require_all``        - when False, intended sections that did not change
                             are not treated as a failure (used where the model
                             legitimately has discretion over how much to touch).
    """
    diff = diff_chunks(before_html, after_html)
    intended: set[str] = set(expected_chunk_ids or ())
    if expected_sections:
        intended |= chunks_of_sections(before_html, expected_sections)
    if expected_text:
        needles = [t.lower() for t in expected_text]
        for cid, residue in residue_map(before_html).items():
            if any(n in visible_text(residue).lower() for n in needles):
                intended.add(cid)

    touched = diff.touched
    new_ids = set(diff.added)
    unintended = sorted((touched - intended) - (new_ids if allow_new else set()))
    missing = sorted(intended - touched) if require_all else []
    return SurgeryVerdict(
        ok=not unintended and not missing,
        intended=sorted(intended),
        unintended=unintended,
        missing=missing,
        unchanged_count=len(diff.unchanged),
        detail=diff.as_dict(),
    )


def text_diff(before: str, after: str, *, label_a: str = "before", label_b: str = "after") -> str:
    """A unified diff a human can read - what "diff week over week" means."""
    return "\n".join(
        difflib.unified_diff(
            (before or "").splitlines(),
            (after or "").splitlines(),
            fromfile=label_a,
            tofile=label_b,
            lineterm="",
            n=2,
        )
    )


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
