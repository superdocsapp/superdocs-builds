"""
Builds the chunk-aligned comparison view: for every chunk id in the source, show the source text next to
each adaptation's text for that same id, with protected chunks marked unchanged (backed by the verifier's
hash check, not a visual guess). Output is a plain data structure here (`ComparisonRow` list) -- rendering
to HTML/React is a presentation concern kept separate so this stays unit-testable without a browser.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.adaptation import AdaptationResult, AdaptationType
from src.chunk_classifier import classify_document


@dataclass
class ComparisonRow:
    chunk_id: str
    kind: str  # "protected" | "prose"
    source_text: str
    adapted_text: dict[AdaptationType, str]
    unchanged_confirmed: bool  # True only for protected chunks that passed hash verification everywhere


def build_comparison(source_html: str, results: dict[AdaptationType, AdaptationResult]) -> list[ComparisonRow]:
    """Aligns source chunks against each adaptation's chunks by DOCUMENT POSITION (ordinal index), not by
    chunk_id. Real-world testing against the live SuperDocs API (2026-08-22) showed chunk ids are reassigned
    on every chat turn, even for untouched content -- an id-keyed lookup found nothing for every single
    chunk. Position is stable as long as the adaptation doesn't add or remove whole sections, which the
    adaptation instructions explicitly ask it not to do. If an adaptation's chunk count differs from the
    source's, this is a real, surfaced limitation (rows past the shorter list read 'MISSING'), not something
    silently papered over."""
    source_chunks = classify_document(source_html)
    adapted_chunk_lists = {
        adaptation_type: classify_document(result.html)
        for adaptation_type, result in results.items()
    }
    # Protected-chunk "unchanged" check is content-based (does this exact chunk's hash appear ANYWHERE in
    # the adapted output), matching verify_protected_chunks' logic -- independent of position, so it stays
    # correct even if position alignment drifts.
    adapted_hash_sets = {
        adaptation_type: {c.content_hash for c in chunks}
        for adaptation_type, chunks in adapted_chunk_lists.items()
    }

    rows = []
    for i, source_chunk in enumerate(source_chunks):
        adapted_text = {}
        all_unchanged = source_chunk.kind == "protected"
        for adaptation_type, chunk_list in adapted_chunk_lists.items():
            adapted_chunk = chunk_list[i] if i < len(chunk_list) else None
            adapted_text[adaptation_type] = adapted_chunk.text if adapted_chunk else "[MISSING — position past end of adapted document]"
            if source_chunk.kind == "protected" and source_chunk.content_hash not in adapted_hash_sets[adaptation_type]:
                all_unchanged = False

        rows.append(ComparisonRow(
            chunk_id=source_chunk.chunk_id, kind=source_chunk.kind, source_text=source_chunk.text,
            adapted_text=adapted_text, unchanged_confirmed=all_unchanged,
        ))
    return rows


def render_html(rows: list[ComparisonRow], adaptation_types: list[AdaptationType]) -> str:
    """Minimal standalone HTML table for the demo video / quick viewing. A real product would render this
    as a React comparison view per the task card's 'chat, Multi-document, images, templates, export'
    surfaces list -- kept as plain HTML here since this module's job is the diffing logic, not UI polish."""
    headers = "".join(f"<th>{t.replace('_', ' ').title()}</th>" for t in adaptation_types)
    body_rows = []
    for row in rows:
        badge = " ✅ unchanged" if row.kind == "protected" and row.unchanged_confirmed else ""
        badge = " ❌ CHANGED (should be protected!)" if row.kind == "protected" and not row.unchanged_confirmed else badge
        cells = "".join(f"<td>{row.adapted_text.get(t, '')}</td>" for t in adaptation_types)
        body_rows.append(
            f"<tr><td><b>{row.kind}{badge}</b><br>{row.source_text}</td>{cells}</tr>"
        )
    return f"""<table border="1" cellpadding="6" style="border-collapse:collapse;width:100%">
<tr><th>Source ({{'kind'}})</th>{headers}</tr>
{''.join(body_rows)}
</table>"""
