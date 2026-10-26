"""Plain-text projection of chunk HTML.

Chunks are stored as the HTML SuperDocs produced, which is right for editing
and rendering and wrong for searching: matching a query against the markup
means `class`, `href` or `p` hit every chunk that has a tag, while a phrase
split across an inline tag (`npm <code>install</code>`) never matches at all.

So search reads a text projection instead. This module is the single
definition of that projection; the equivalent expression in
`003_chunk_text.sql` exists only to backfill rows written before it.
"""

import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Only the entities SuperDocs actually emits. A general entity decoder would
# also turn a documented literal like "&lt;tag&gt;" into markup-looking text,
# which is worse for a search index than leaving it alone.
_ENTITIES = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
}


def html_to_text(html: str | None) -> str:
    """Collapse chunk HTML to searchable text.

    Tags become spaces rather than being deleted, so `<td>a</td><td>b</td>`
    reads as "a b" and not "ab" — table cells would otherwise fuse into words
    that appear nowhere in the document.
    """
    if not html:
        return ""
    text = _TAG.sub(" ", html)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    return _WS.sub(" ", text).strip()


def snippet_around(text: str, match_start: int, match_len: int, radius: int = 90) -> dict:
    """A window of text around a match, with the match's offset inside it.

    Returns offsets rather than pre-highlighted markup so the caller decides
    how to render — and so the highlight cannot be spoofed by document content
    that happens to contain markup.
    """
    if match_start < 0:
        head = text[: radius * 2]
        return {
            "text": head + ("…" if len(text) > len(head) else ""),
            "match_start": -1,
            "match_length": 0,
        }

    start = max(0, match_start - radius)
    end = min(len(text), match_start + match_len + radius)
    body = text[start:end]

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""

    return {
        "text": f"{prefix}{body}{suffix}",
        "match_start": (match_start - start) + len(prefix),
        "match_length": match_len,
    }
