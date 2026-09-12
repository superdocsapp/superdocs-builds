import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: str
    text: str
    char_span: tuple[int, int]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", (text or "").lower())


def chunk_documents(docs: list[dict]) -> list[Chunk]:
    """Partition each document into paragraph-like chunks with stable IDs."""
    chunks: list[Chunk] = []
    for doc in docs:
        doc_id = str(doc.get("doc_id") or doc.get("id") or "doc")
        text = str(doc.get("text") or "")
        parts = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
        if not parts:
            parts = [text.strip()] if text.strip() else []
        cursor = 0
        for index, part in enumerate(parts, start=1):
            chunk_id = f"{doc_id}-{index}"
            start = text.find(part, cursor)
            if start < 0:
                start = cursor
            end = start + len(part)
            cursor = end
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    text=part,
                    char_span=(start, end),
                )
            )
    return chunks


def _bm25_score(query: str, chunk: Chunk, doc_freq: Counter[str], doc_count: int) -> float:
    query_terms = _tokenize(query)
    if not query_terms:
        return 0.0
    term_counts = Counter(_tokenize(chunk.text))
    score = 0.0
    for term in set(query_terms):
        tf = term_counts.get(term, 0)
        df = doc_freq.get(term, 0)
        if tf == 0 or df == 0:
            continue
        idf = math.log((doc_count + 1) / (df + 1)) + 1.0
        score += (tf / (tf + 1.5)) * idf
    return score


def _overlap_score(query: str, chunk: Chunk) -> float:
    query_terms = set(_tokenize(query))
    chunk_terms = set(_tokenize(chunk.text))
    if not query_terms:
        return 0.0
    return len(query_terms & chunk_terms) / len(query_terms)


def hybrid_search(query: str, chunks: Iterable[Chunk], top_k: int = 8) -> list[Chunk]:
    """Simple hybrid retrieval with BM25-like term scoring and overlap ranking."""
    chunks = list(chunks)
    if not chunks:
        return []
    doc_count = len({chunk.doc_id for chunk in chunks})
    doc_freq = Counter()
    for chunk in chunks:
        doc_freq.update(set(_tokenize(chunk.text)))

    ranked = []
    for chunk in chunks:
        bm25 = _bm25_score(query, chunk, doc_freq, doc_count)
        overlap = _overlap_score(query, chunk)
        ranked.append((bm25 + overlap, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in ranked[:top_k]]
