"""
Given SuperDocs' chunk-id-tagged doc HTML (or plain markdown, for offline testing without a live API), finds
which chunks mention a given function name. Deliberately simple name-based matching, not semantic search --
see README's "what's honestly a gap" section for why, and the asymmetry this drives: a MISS (function
genuinely documented but matching fails) is worse than a false positive here, because a miss means DocSync
proposes nothing for an actually-stale doc section. So matching is deliberately loose: bare name, name
inside backticks, name inside a markdown link, name as part of a code block -- all count as a hit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DocChunk:
    chunk_id: str
    text: str


def parse_markdown_chunks(markdown: str) -> list[DocChunk]:
    """Splits markdown into paragraph/heading-level chunks with synthetic ids, for offline testing without
    a live SuperDocs upload. Real usage gets chunks directly from SuperDocs' parsed HTML instead (see
    sync_engine.py), which already carries real chunk ids -- this function exists purely so doc_index's
    matching logic can be tested without a network call."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", markdown) if b.strip()]
    return [DocChunk(chunk_id=f"md-{i}", text=block) for i, block in enumerate(blocks)]


def _name_appears(function_name: str, text: str) -> bool:
    # Word-boundary match so "get" doesn't match inside "getter" or "budget". Covers bare mentions,
    # backtick-code mentions, and mentions inside a code block/link -- all normalize to plain word-boundary
    # matching once we're working on raw text.
    pattern = r"\b" + re.escape(function_name) + r"\b"
    return re.search(pattern, text) is not None


def find_doc_references(chunks: list[DocChunk], function_name: str) -> list[DocChunk]:
    return [c for c in chunks if _name_appears(function_name, c.text)]
