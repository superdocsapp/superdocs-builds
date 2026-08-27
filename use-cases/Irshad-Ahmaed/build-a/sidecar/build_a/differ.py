"""Client-side document diffing engine.

Compares pre-edit and post-edit HTML at the paragraph level to identify
changed content and their positions. Uses SuperDocs chunk IDs when available,
falls back to text similarity matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from bs4 import BeautifulSoup


class ChangeType(StrEnum):
    MODIFIED = "modified"
    ADDED = "added"
    REMOVED = "removed"


@dataclass
class ParagraphDiff:
    position: int
    change_type: ChangeType
    old_text: str
    new_text: str
    chunk_id: str | None = None


@dataclass
class DiffResult:
    changed: list[ParagraphDiff]
    total_paragraphs_old: int
    total_paragraphs_new: int

    @property
    def has_changes(self) -> bool:
        return len(self.changed) > 0

    @property
    def changed_positions(self) -> list[int]:
        return [d.position for d in self.changed]

    def to_instruction_payload(self) -> str:
        """Format diff for injection into a chat instruction."""
        tag_map = {"modified": "~", "added": "+", "removed": "-"}
        lines = []
        for d in self.changed:
            tag = tag_map.get(d.change_type.value, "?")
            lines.append(f"[{tag}] Paragraph {d.position}: {d.new_text[:200]}")
        return "\n".join(lines)


def extract_paragraphs(html: str) -> list[tuple[str, str | None]]:
    """Extract paragraphs from HTML, returning (text, chunk_id) pairs.

    Captures block-level text elements plus any direct text children of body
    that aren't inside a block element (handles SuperDocs-generated HTML where
    content may sit directly under body). Avoids double-counting nested blocks
    (e.g. <div><p>text</p></div> only counts the inner <p>).
    """
    soup = BeautifulSoup(html, "html.parser")
    block_tags = {
        "p", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "td", "th", "blockquote",
    }
    container_tags = {"div", "section", "article", "main", "aside", "nav", "header", "footer"}
    results: list[tuple[str, str | None]] = []

    for el in soup.find_all(list(block_tags | container_tags)):
        # Skip containers — only extract leaf block elements
        if el.name in container_tags and el.find(list(block_tags)):
            continue
        text = el.get_text(strip=True)
        if not text:
            continue
        chunk_id: str | None = None
        data_chunk = el.get("data-chunk-id") or el.get("data-chunk")
        if data_chunk:
            chunk_id = str(data_chunk)
        results.append((text, chunk_id))

    return results


def extract_from_chunk_diffs(chunk_diffs: list[dict]) -> list[ParagraphDiff]:
    """Process chunk_diffs from compact mode API response."""
    diffs: list[ParagraphDiff] = []
    for i, cd in enumerate(chunk_diffs):
        chunk_id = cd.get("chunk_id")
        old = cd.get("old_text", "")
        new = cd.get("new_text", "")
        if old == new:
            continue
        if not old:
            ct = ChangeType.ADDED
        elif not new:
            ct = ChangeType.REMOVED
        else:
            ct = ChangeType.MODIFIED
        diffs.append(ParagraphDiff(
            position=i, change_type=ct, old_text=old, new_text=new, chunk_id=chunk_id
        ))
    return diffs


def diff_paragraphs(
    old_paras: list[tuple[str, str | None]],
    new_paras: list[tuple[str, str | None]],
) -> list[ParagraphDiff]:
    """Diff two lists of (text, chunk_id) pairs using sequence matching."""
    if not old_paras and not new_paras:
        return []
    old_texts = [p[0] for p in old_paras]
    new_texts = [p[0] for p in new_paras]
    old_chunks = [p[1] for p in old_paras]
    new_chunks = [p[1] for p in new_paras]

    matcher = SequenceMatcher(None, old_texts, new_texts, autojunk=False)
    diffs: list[ParagraphDiff] = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        elif op == "replace":
            old_count = i2 - i1
            new_count = j2 - j1
            # Pair up the overlapping portion as modified
            paired = min(old_count, new_count)
            for k in range(paired):
                diffs.append(ParagraphDiff(
                    position=i1 + k,
                    change_type=ChangeType.MODIFIED,
                    old_text=old_texts[i1 + k],
                    new_text=new_texts[j1 + k],
                    chunk_id=new_chunks[j1 + k],
                ))
            # Extra old paragraphs beyond the new count are removed
            for k in range(paired, old_count):
                diffs.append(ParagraphDiff(
                    position=i1 + k,
                    change_type=ChangeType.REMOVED,
                    old_text=old_texts[i1 + k],
                    new_text="",
                    chunk_id=old_chunks[i1 + k],
                ))
            # Extra new paragraphs beyond the old count are added
            for k in range(paired, new_count):
                diffs.append(ParagraphDiff(
                    position=j1 + k,
                    change_type=ChangeType.ADDED,
                    old_text="",
                    new_text=new_texts[j1 + k],
                    chunk_id=new_chunks[j1 + k],
                ))
        elif op == "insert":
            for k in range(j1, j2):
                diffs.append(ParagraphDiff(
                    position=k,
                    change_type=ChangeType.ADDED,
                    old_text="",
                    new_text=new_texts[k],
                    chunk_id=new_chunks[k],
                ))
        elif op == "delete":
            for k in range(i1, i2):
                diffs.append(ParagraphDiff(
                    position=k,
                    change_type=ChangeType.REMOVED,
                    old_text=old_texts[k],
                    new_text="",
                    chunk_id=old_chunks[k],
                ))

    return diffs


class DocDiffer:
    """Document diffing engine.

    Compares pre-edit and post-edit HTML at paragraph level.
    Uses chunk IDs for matching when available, falls back to text similarity.
    """

    def diff(self, pre_html: str, post_html: str) -> DiffResult:
        """Diff two HTML strings and return structured change list."""
        old_paras = extract_paragraphs(pre_html)
        new_paras = extract_paragraphs(post_html)

        if not old_paras and not new_paras:
            return DiffResult(changed=[], total_paragraphs_old=0, total_paragraphs_new=0)

        diffs = diff_paragraphs(old_paras, new_paras)

        return DiffResult(
            changed=diffs,
            total_paragraphs_old=len(old_paras),
            total_paragraphs_new=len(new_paras),
        )

    def from_chunk_diffs(self, chunk_diffs: list[dict]) -> DiffResult:
        """Build a DiffResult from compact mode chunk_diffs."""
        diffs = extract_from_chunk_diffs(chunk_diffs)
        return DiffResult(
            changed=diffs,
            total_paragraphs_old=0,
            total_paragraphs_new=0,
        )
