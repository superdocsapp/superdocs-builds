"""How SuperDocs detects editable blocks.

SuperDocs assigns a ``data-chunk-id`` to each block-level element (heading, paragraph, list
item, table row, ...). We model that with a small tag set. Our outbound HTML (``notion/html.py``)
deliberately places each editable block's marker on one of these leaf-ish tags, so structural
wrappers (``details``/``table``/``aside``) are never mistaken for editable content.
"""

from __future__ import annotations

from collections.abc import Iterator

from lxml.html import HtmlElement

# Leaf-ish block tags that carry editable text. Wrappers (details, table, ul, ol, aside,
# section) are intentionally excluded so a container is never chunked as if it were content.
BLOCK_TAGS = frozenset({"h1", "h2", "h3", "p", "blockquote", "pre", "summary", "li", "tr", "div"})


def iter_block_elements(root: HtmlElement) -> Iterator[HtmlElement]:
    """Yield block-level elements in document order.

    Iterates the descendants of ``root``, so the parse wrapper itself is never yielded — lxml
    wraps a body fragment in a ``div``, and that artifact must not be mistaken for content.
    """
    for el in root.iterdescendants():
        if isinstance(el.tag, str) and el.tag in BLOCK_TAGS:
            yield el
