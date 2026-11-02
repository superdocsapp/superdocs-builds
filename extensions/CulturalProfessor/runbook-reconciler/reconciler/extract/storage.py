"""Confluence storage format, parsed **only to locate**.

This is the file the whole promise rests on, so the rule it obeys is worth
stating before any code: **nothing here ever produces a modified document.** It
reads a body and returns offsets into that exact string. The edit is a splice
performed by `confluence/splice.py` on the original bytes, and everything
outside the spliced range is byte-identical because it was never re-serialized.

Parse → modify → re-serialize is the obvious design and it is how you silently
vandalise a four-year-old wiki. Confluence storage format is XHTML with
undeclared namespaces (`ac:`, `ri:`), macros whose parameters are meaningful,
`&nbsp;` in places a serializer will normalise, and attribute ordering that
round-trips through most libraries changed. A page that comes back "the same"
except that thirty macros lost their `ac:macro-id` is a page whose history is now
useless.

## Why not ElementTree

Because it refuses the input. `<ac:structured-macro>` with no `xmlns:ac`
declaration is a parse error, so every caller ends up wrapping the body in a
synthetic root with fake namespace declarations — at which point the offsets no
longer refer to the document Confluence sent, which is the one thing this module
must guarantee. A small tolerant scanner is both less code and more correct
here.

## Blocks, and why tables descend

A "block" is the unit a claim is anchored to. Paragraphs and headings are
blocks, and so are individual `<td>`, `<th>` and `<li>` elements: a DR plan puts
its retention period in a table cell, and anchoring that claim to the whole
`<table>` would mean a proposed edit whose smallest possible unit is the entire
table. Descending into cells is what keeps "one contiguous changed range" small
enough to be reviewable.

## The allowlist

A block is editable when every element inside it is one this tool can leave
untouched with confidence. The code macro is the interesting exception: it is
allowed, but only its `<![CDATA[…]]>` body is editable — that is plain text by
definition, so replacing a span of it cannot corrupt the macro around it. Every
other macro, every `ac:link`, user mention and attachment refuses the splice and
the finding falls back to an inline comment.

`editable` is therefore not a measure of confidence in the finding. It is a
statement about whether this tool can perform the edit without risk of damage,
and a capability honestly absent from a path beats one present and broken.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field

#: Tags whose content this tool can reconstruct faithfully.
ALLOWED_TAGS = frozenset(
    {
        "p", "h1", "h2", "h3", "h4", "h5", "h6",
        "strong", "em", "b", "i", "u", "s", "sub", "sup",
        "code", "pre", "blockquote", "a", "br", "span",
        "ul", "ol", "li",
        "table", "thead", "tbody", "tfoot", "tr", "td", "th", "colgroup", "col",
        "hr", "div",
    }
)  # fmt: skip

#: Elements that are a claim's home. `ac:structured-macro` is one because a code
#: macro is where the commands live, and commands are half of what a runbook
#: asserts. Its editability is decided separately: a code macro's CDATA is
#: spliceable, every other macro refuses.
LEAF_BLOCKS = frozenset(
    {"p", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "li", "blockquote", "ac:structured-macro"}
)

#: Elements walked through rather than treated as a block themselves.
CONTAINERS = frozenset(
    {"table", "thead", "tbody", "tfoot", "tr", "ul", "ol", "colgroup", "div", "ac:layout",
     "ac:layout-section", "ac:layout-cell"}
)  # fmt: skip

VOID_TAGS = frozenset({"br", "hr", "img", "col", "ri:user", "ri:attachment", "ri:page"})

HEADINGS = {f"h{n}": n for n in range(1, 7)}

_TAG = re.compile(r"<(/?)([A-Za-z][\w:.-]*)((?:\s+[\w:.-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>")
_ATTR = re.compile(r"([\w:.-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_ENTITY = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]{1,31});")
_CDATA_OPEN = "<![CDATA["
_CDATA_CLOSE = "]]>"
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

#: The four ways a runbook says "put your own value here", as spellings rather
#: than as guesses. Runbooks are written with them deliberately, and treating one
#: as a value that does not exist is the false positive that eats this product
#: (risk 3 in the brief).
#:
#: Only angle brackets used to be recognised, and a negative corpus written to
#: provoke exactly this found the rest in one run: `kubectl -n $NAMESPACE
#: rollout restart deploy/SERVICE_HERE` produced a claim that `SERVICE_HERE` is
#: a deployment, and because it is the claim that names the page's subject
#: service, the page-level pass then condemned the whole page as a runbook for a
#: service that no longer exists.
#:
#: What is *not* here matters as much. A bare `NAMESPACE` or `SERVICE` in caps
#: is not included: it could be a real resource, and a placeholder convention
#: that swallows real names is a checker that reports drift-free estates. Every
#: pattern below carries a marker that prose does not — brackets, a `$`, or an
#: explicit `YOUR_`/`_HERE` affix. A team spelling them another way adds theirs
#: to `placeholder_patterns` in `config/mappings.yaml`, which is what the README
#: has always promised and what previously had nowhere to go.
DEFAULT_PLACEHOLDER_PATTERNS: tuple[str, ...] = (
    r"<[a-z][a-z0-9 _-]*>",  # <your-namespace>, <cluster>
    r"\{\{[^}]{1,64}\}\}",  # {{ namespace }}, {{service}}
    r"\$\{?[A-Z][A-Z0-9_]*\}?",  # $NAMESPACE, ${SERVICE}
    r"\b(?:YOUR|MY)_[A-Z0-9_]+\b|\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_HERE\b",  # SERVICE_HERE
)

PLACEHOLDER = re.compile("|".join(DEFAULT_PLACEHOLDER_PATTERNS), re.IGNORECASE)


def placeholder_matcher(extra: tuple[str, ...] = ()) -> re.Pattern[str]:
    """The convention, plus whatever this estate spells differently.

    A bad pattern in a config file must not take the checker down with it, so an
    entry that does not compile is dropped rather than raised — the cost is that
    one convention going unrecognised, which is a false positive somebody can
    see, against a tool that will not start, which is not.
    """
    patterns = list(DEFAULT_PLACEHOLDER_PATTERNS)
    for pattern in extra:
        try:
            re.compile(pattern)
        except re.error:
            continue
        patterns.append(pattern)
    return re.compile("|".join(patterns), re.IGNORECASE)


@dataclass(frozen=True)
class Region:
    """A run of editable characters in the body, and what it is.

    `kind` is `text` for character data and `attr` for an attribute value —
    a dead dashboard link is fixed by rewriting an `href`, and an attribute
    value is exactly as spliceable as a text run. `cdata` is the inside of a
    code macro.
    """

    start: int
    end: int
    kind: str = "text"
    attribute: str | None = None


@dataclass(frozen=True)
class Block:
    """One anchorable passage of a document."""

    tag: str
    index: int
    start: int
    end: int
    inner_start: int
    inner_end: int
    heading_path: tuple[str, ...]
    text: str
    #: `spans[i]` is the (start, end) byte range of `text[i]` in the body. An
    #: entity is one character of text and six bytes of body, and a splice that
    #: gets that wrong writes into the middle of `&nbsp;`.
    spans: tuple[tuple[int, int], ...]
    regions: tuple[Region, ...]
    tags_inside: frozenset[str]
    macros_inside: frozenset[str]
    editable: bool
    refusal: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    links: tuple[tuple[str, Region], ...] = ()
    #: Ranges of `text` that were wrapped in `<code>`, in text coordinates.
    #: Runbooks put resource names in code spans and prose around them, and the
    #: distinction is worth keeping: `payments-api` inside `<code>` is a claim
    #: about a resource, and the same word in a sentence is usually not.
    code_spans: tuple[tuple[int, int], ...] = ()

    @property
    def content_hash(self) -> str:
        """Identity of the passage's text, for re-resolving after a change."""
        return hashlib.sha256(self.text.strip().encode("utf-8")).hexdigest()[:16]

    @property
    def has_placeholder(self) -> bool:
        return bool(PLACEHOLDER.search(self.text))

    def body_range(self, text_start: int, text_end: int) -> tuple[int, int]:
        """Map a slice of `text` back to a byte range in the body.

        The only way a caller should ever turn a regex match into something to
        splice. Doing the arithmetic by hand is how you end up one `&nbsp;`
        adrift and rewriting half a tag.
        """
        if not self.spans or text_start >= text_end:
            raise ValueError("empty range has no body position")
        return self.spans[text_start][0], self.spans[text_end - 1][1]

    def crosses_markup(self, text_start: int, text_end: int) -> bool:
        """Whether the byte range for this text also contains tags.

        A value can be adjacent in the text and separated in the document:
        `<code>payments</code>.` reads as `payments.` and the two characters
        either side of the boundary are eleven bytes apart. Splicing that range
        would rewrite the closing tag along with the value.

        The extractor asks this and refuses the splice when the answer is yes,
        which turns a class of silent markup corruption into a comment for a
        human. It found a real one in the corpus: a namespace claim whose
        pattern had swallowed a sentence-ending full stop.
        """
        return any(
            self.spans[i][1] != self.spans[i + 1][0] for i in range(text_start, text_end - 1)
        )


@dataclass(frozen=True)
class Document:
    page_id: str
    body: str
    blocks: tuple[Block, ...]
    version: int = 1
    title: str = ""

    def block_at(self, index: int) -> Block | None:
        return next((b for b in self.blocks if b.index == index), None)

    def find_block(self, heading_path: tuple[str, ...], content_hash: str) -> Block | None:
        """Re-resolve an anchor against a freshly read body.

        Heading path plus content hash, never a stored offset: offsets belong to
        the version they were read from. A miss here means the passage changed
        under us, and the caller escalates rather than guessing.
        """
        for block in self.blocks:
            if block.heading_path == heading_path and block.content_hash == content_hash:
                return block
        return None


# ------------------------------------------------------------------ parse --


@dataclass
class _Element:
    tag: str
    start: int
    inner_start: int
    attributes: dict[str, str]


def parse(body: str, page_id: str = "", version: int = 1, title: str = "") -> Document:
    """Blocks and their offsets. The body itself is returned unchanged."""
    blocks: list[Block] = []
    stack: list[_Element] = []
    heading_stack: list[tuple[int, str]] = []
    #: The depth of the block currently open, so a `<p>` inside a `<td>` does
    #: not open a second one. `None` means no block is open.
    block_depth: int | None = None
    index = 0

    pos = 0
    length = len(body)
    while pos < length:
        if body.startswith(_CDATA_OPEN, pos):
            close = body.find(_CDATA_CLOSE, pos)
            pos = length if close == -1 else close + len(_CDATA_CLOSE)
            continue
        match = _TAG.search(body, pos)
        if not match:
            break

        closing, tag, raw_attributes, self_closing = match.groups()
        tag = tag.lower()

        if closing:
            depth = _depth_of(stack, tag)
            if depth is not None:
                element = stack[depth]
                del stack[depth:]
                if block_depth is not None and depth <= block_depth:
                    if depth == block_depth:
                        blocks.append(
                            _build_block(
                                body,
                                element,
                                match.end(),
                                match.start(),
                                tuple(h for _, h in heading_stack),
                                index,
                            )
                        )
                        index += 1
                    # An unclosed tag inside the block closes it too: the block
                    # is over either way, and leaving block_depth set here means
                    # every later paragraph is swallowed into it.
                    block_depth = None
                if tag in HEADINGS:
                    _push_heading(
                        heading_stack,
                        HEADINGS[tag],
                        _plain_text(body, element.inner_start, match.start()),
                    )
            pos = match.end()
            continue

        if self_closing or tag in VOID_TAGS:
            pos = match.end()
            continue

        stack.append(_Element(tag, match.start(), match.end(), _attributes(raw_attributes)))
        if block_depth is None and tag in LEAF_BLOCKS:
            block_depth = len(stack) - 1
        pos = match.end()

    return Document(
        page_id=page_id,
        body=body,
        blocks=tuple(blocks),
        version=version,
        title=title,
    )


def occurrence_of(blocks: tuple[Block, ...], block: Block) -> int:
    """How many identical passages under the same heading came before this one."""
    return sum(
        1
        for other in blocks
        if other.index < block.index
        and other.heading_path == block.heading_path
        and other.content_hash == block.content_hash
    )


def _push_heading(stack: list[tuple[int, str]], level: int, text: str) -> None:
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, text.strip()))


def _attributes(raw: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2) or m.group(3) or "" for m in _ATTR.finditer(raw)}


def _depth_of(stack: list[_Element], tag: str) -> int | None:
    for depth in range(len(stack) - 1, -1, -1):
        if stack[depth].tag == tag:
            return depth
    return None


def _build_block(
    body: str,
    element: _Element,
    open_end: int,
    close_start: int,
    heading_path: tuple[str, ...],
    index: int,
) -> Block:
    own_macro = (
        element.attributes.get("ac:name", "unknown")
        if element.tag == "ac:structured-macro"
        else None
    )
    walked = _walk(body, element.inner_start, close_start, own_macro)
    text, spans, regions, tags_inside, macros, links, code_spans = walked
    if own_macro:
        macros.add(own_macro)
    editable, refusal = _editability(tags_inside, macros)
    return Block(
        tag=element.tag,
        index=index,
        start=element.start,
        end=open_end,
        inner_start=element.inner_start,
        inner_end=close_start,
        heading_path=heading_path,
        text=text,
        spans=tuple(spans),
        regions=tuple(regions),
        tags_inside=frozenset(tags_inside),
        macros_inside=frozenset(macros),
        editable=editable,
        refusal=refusal,
        attributes=dict(element.attributes),
        links=tuple(links),
        code_spans=tuple(code_spans),
    )


def _walk(body: str, start: int, end: int, own_macro: str | None = None) -> tuple[
    str,
    list[tuple[int, int]],
    list[Region],
    set[str],
    set[str],
    list[tuple[str, Region]],
    list[tuple[int, int]],
]:
    """Text, offsets and structure of one block's contents.

    Two rules, and both are about not matching claim patterns against things
    that are not prose:

    - **Character data inside any `ac:`/`ri:` element is skipped.** A status
      macro's colour parameter is decoration, and a checker that reads it will
      eventually find a threshold in one.
    - **CDATA is taken only when the enclosing macro is a code macro.** That is
      the command an engineer will actually type, and it is the whole reason
      commands are checkable. `own_macro` is how a block that *is* the code
      macro says so, since its own opening tag was consumed by the caller.
    """
    pieces: list[str] = []
    spans: list[tuple[int, int]] = []
    regions: list[Region] = []
    tags_inside: set[str] = set()
    macros: set[str] = set()
    links: list[tuple[str, Region]] = []

    code_spans: list[tuple[int, int]] = []
    open_tags: list[str] = []
    macro_stack: list[str] = [own_macro] if own_macro else []
    ac_depth = 0
    code_depth = 0
    pos = start

    while pos < end:
        if body.startswith(_CDATA_OPEN, pos):
            close = body.find(_CDATA_CLOSE, pos)
            close = end if close == -1 else close
            inner_start = pos + len(_CDATA_OPEN)
            if macro_stack and macro_stack[-1] == "code":
                _append_literal(body, inner_start, close, pieces, spans)
                regions.append(Region(inner_start, close, kind="cdata"))
            pos = min(close + len(_CDATA_CLOSE), end) if close < end else end
            continue

        match = _TAG.search(body, pos)
        if not match or match.start() >= end:
            if ac_depth == 0:
                _append_marked(body, pos, end, pieces, spans, regions, code_depth, code_spans)
            break

        if ac_depth == 0 and match.start() > pos:
            _append_marked(body, pos, match.start(), pieces, spans, regions, code_depth, code_spans)

        closing, tag, raw_attributes, self_closing = match.groups()
        tag = tag.lower()
        tags_inside.add(tag)

        if closing:
            if tag in open_tags:
                while open_tags and open_tags.pop() != tag:
                    pass
            if tag.startswith(("ac:", "ri:")):
                ac_depth = max(0, ac_depth - 1)
            if tag == "code":
                code_depth = max(0, code_depth - 1)
            if tag == "ac:structured-macro" and macro_stack:
                macro_stack.pop()
            pos = match.end()
            continue

        attributes = _attributes(raw_attributes)
        if tag == "ac:structured-macro":
            name = attributes.get("ac:name", "unknown")
            macros.add(name)
            macro_stack.append(name)
        if tag == "a" and ac_depth == 0 and "href" in attributes:
            href_start = body.find(attributes["href"], match.start(), match.end())
            if href_start != -1:
                links.append(
                    (
                        attributes["href"],
                        Region(href_start, href_start + len(attributes["href"]), "attr", "href"),
                    )
                )

        if not (self_closing or tag in VOID_TAGS):
            open_tags.append(tag)
            if tag.startswith(("ac:", "ri:")):
                ac_depth += 1
            if tag == "code":
                code_depth += 1
        pos = match.end()

    return "".join(pieces), spans, regions, tags_inside, macros, links, code_spans


def _append_marked(
    body: str,
    start: int,
    end: int,
    pieces: list[str],
    spans: list[tuple[int, int]],
    regions: list[Region],
    code_depth: int,
    code_spans: list[tuple[int, int]],
) -> None:
    """Append a text run, remembering whether it was inside `<code>`.

    Every entry in `pieces` is exactly one character of `text`, so its length is
    the current text index. That invariant is what makes recording a text-space
    span here a subtraction rather than a second pass.
    """
    if end <= start:
        return
    mark = len(pieces)
    _append_text(body, start, end, pieces, spans, regions)
    if code_depth > 0 and len(pieces) > mark:
        code_spans.append((mark, len(pieces)))


def _append_text(
    body: str,
    start: int,
    end: int,
    pieces: list[str],
    spans: list[tuple[int, int]],
    regions: list[Region],
) -> None:
    if end <= start:
        return
    _append_decoded(body, start, end, pieces, spans)
    regions.append(Region(start, end, kind="text"))


def _append_decoded(
    body: str, start: int, end: int, pieces: list[str], spans: list[tuple[int, int]]
) -> None:
    """Decode entities while keeping every character's byte range.

    `&nbsp;` is one character of text and six bytes of document. Losing that
    correspondence is how a splice lands in the middle of an entity.
    """
    pos = start
    while pos < end:
        if body[pos] == "&":
            match = _ENTITY.match(body, pos)
            if match and match.end() <= end:
                pieces.append(html.unescape(match.group(0)))
                spans.append((pos, match.end()))
                pos = match.end()
                continue
        pieces.append(body[pos])
        spans.append((pos, pos + 1))
        pos += 1


def _append_literal(
    body: str, start: int, end: int, pieces: list[str], spans: list[tuple[int, int]]
) -> None:
    """CDATA is literal: no entity decoding, one byte per character."""
    for pos in range(start, end):
        pieces.append(body[pos])
        spans.append((pos, pos + 1))


def _editability(tags_inside: set[str], macros: set[str]) -> tuple[bool, str | None]:
    unknown_macros = sorted(macros - {"code"})
    if unknown_macros:
        return (
            False,
            f"contains the {', '.join(unknown_macros)} macro, which this tool cannot rebuild",
        )
    foreign = sorted(
        tag
        for tag in tags_inside
        if tag not in ALLOWED_TAGS
        and tag not in CONTAINERS
        and tag
        not in {"ac:structured-macro", "ac:parameter", "ac:plain-text-body", "ac:rich-text-body"}
    )
    if foreign:
        return False, f"contains {', '.join(foreign)}, which is outside the node allowlist"
    return True, None


def _plain_text(body: str, start: int, end: int) -> str:
    pieces: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        match = _TAG.search(body, pos)
        if not match or match.start() >= end:
            _append_decoded(body, pos, end, pieces, spans)
            break
        _append_decoded(body, pos, match.start(), pieces, spans)
        pos = match.end()
    return "".join(pieces)


__all__ = [
    "ALLOWED_TAGS",
    "CONTAINERS",
    "LEAF_BLOCKS",
    "PLACEHOLDER",
    "Block",
    "Document",
    "Region",
    "occurrence_of",
    "parse",
]
