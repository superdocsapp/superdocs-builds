"""Computes the evaluation metrics table for a finished Paper — all
derived from data the pipeline already produces, no extra LLM calls
except redundancy (which reuses embeddings we already have access to)."""
from __future__ import annotations
from itertools import combinations
import numpy as np

from src.models import Paper, RunLog, RunAction
from src.retrieval import RetrievalIndex


def citation_support_rate(paper: Paper) -> dict:
    total = sum(len(s.citations) for s in paper.sections)
    verified = sum(1 for s in paper.sections for c in s.citations if c.verified)
    per_section = {
        s.title: (
            sum(1 for c in s.citations if c.verified) / len(s.citations)
            if s.citations else None
        )
        for s in paper.sections
    }
    return {
        "overall": verified / total if total else None,
        "verified": verified, "total": total,
        "per_section": per_section,
    }


def revision_rate(run_logs: list[RunLog]) -> dict:
    revised_sections = set()
    for log in run_logs:
        if log.action == RunAction.REVISE:
            revised_sections.update(log.sections_touched)
    total_sections = len({sid for log in run_logs for sid in log.sections_touched})
    return {
        "sections_revised": len(revised_sections),
        "total_sections": total_sections,
        "rate": len(revised_sections) / total_sections if total_sections else None,
    }


def source_coverage(paper: Paper, chunk_id_to_source_id: dict[str, str]) -> dict:
    cited_chunks = {c.passage_ref for s in paper.sections for c in s.citations}
    total_chunks = len(chunk_id_to_source_id)
    return {
        "cited_chunks": len(cited_chunks), "total_chunks": total_chunks,
        "rate": len(cited_chunks) / total_chunks if total_chunks else None,
    }


def citation_density(paper: Paper) -> dict:
    per_section = {}
    for s in paper.sections:
        word_count = len(s.content.split()) if s.content else 0
        per_section[s.title] = (
            len(s.citations) / word_count if word_count else None
        )
    return {"per_section": per_section}


def section_redundancy(paper: Paper, embed_fn, threshold: float = 0.90) -> dict:
    """Flags pairs of sections whose content is suspiciously similar —
    directly targets the repetition issue observed in early runs.
    Cosine similarity on section-content embeddings."""
    sections_with_content = [s for s in paper.sections if s.content]
    if len(sections_with_content) < 2:
        return {"flagged_pairs": []}

    embeddings = embed_fn([s.content for s in sections_with_content])
    vectors = np.array(embeddings)
    norms = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    flagged = []
    for i, j in combinations(range(len(sections_with_content)), 2):
        similarity = float(np.dot(norms[i], norms[j]))
        if similarity >= threshold:
            flagged.append({
                "section_a": sections_with_content[i].title,
                "section_b": sections_with_content[j].title,
                "similarity": similarity,
            })
    return {"flagged_pairs": flagged}


def compute_all_metrics(
    paper: Paper, run_logs: list[RunLog],
    chunk_id_to_source_id: dict[str, str], embed_fn,
) -> dict:
    return {
        "citation_support": citation_support_rate(paper),
        "revision": revision_rate(run_logs),
        "source_coverage": source_coverage(paper, chunk_id_to_source_id),
        "citation_density": citation_density(paper),
        "redundancy": section_redundancy(paper, embed_fn),
    }