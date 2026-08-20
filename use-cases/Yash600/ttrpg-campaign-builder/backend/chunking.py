"""
chunking.py -- pure text-normalization utilities, deliberately
dependency-free (stdlib only: re, hashlib) and side-effect-free so they can
be unit tested without a live SuperDocs key or a database.

v1 of this module parsed SuperDocs' per-chunk HTML (one data-chunk-id per
paragraph/heading/table) into logical sections, because the old Entity/
Reference model tracked staleness at chunk granularity. v2's data model
(see models.py) versions WHOLE documents instead -- every edit produces a
new DocumentVersion row holding the full document HTML/text, and
DocumentLink staleness compares version NUMBERS, not chunk hashes. That
removes the need for chunk parsing entirely: this module now only holds
the text-normalization + hashing helpers that are still useful (turning a
document's HTML into plain text for DocumentVersion.content_text and
detecting true no-op edits before bumping a version needlessly).
"""

from __future__ import annotations

import hashlib
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalize_text(html: str) -> str:
    """
    Strip tags and collapse whitespace -- used both to derive
    DocumentVersion.content_text from content_html, and as the basis for
    content_hash()'s stability guarantee (formatting-only changes, like
    attribute reordering, don't count as a real edit).

    >>> normalize_text('<p>  Hello   <b>world</b>. </p>')
    'Hello world .'
    """
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&mdash;", "—").replace("&ndash;", "–").replace("&amp;", "&")
    text = _WS_RE.sub(" ", text).strip()
    return text


def content_hash(html: str) -> str:
    """sha256 hex digest of the normalized text of a document's HTML."""
    return hashlib.sha256(normalize_text(html).encode("utf-8")).hexdigest()
