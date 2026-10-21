"""Shared citation-verification logic. Used by both pipeline/extract.py
(stage 2) and pipeline/reconcile.py (stage 3) -- moved here rather than
duplicated or imported cross-stage, since it's genuinely a `core/` concern:
the same "never trust a claimed quote, verify it against the actual source
text" enforcement applies wherever a stage cites a document.
"""

from __future__ import annotations


def _normalize(text: str) -> str:
    return " ".join(text.split())


def quote_is_verifiable(quote: str, raw_text: str) -> bool:
    """Whitespace-normalized substring check. The model may reproduce a quote
    with slightly different line wrapping than the source (PDFs and copy-paste
    both do this), but the words themselves must genuinely appear, in order,
    in the document -- this is not a fuzzy/similarity match."""
    if not quote.strip():
        return False
    return _normalize(quote) in _normalize(raw_text)
