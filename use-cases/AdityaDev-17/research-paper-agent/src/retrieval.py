from __future__ import annotations
import uuid
import numpy as np
import faiss
from openai import OpenAI

from src.models import Source, SourceChunk


CHUNK_SIZE_CHARS = 1000
CHUNK_OVERLAP_CHARS = 150


def chunk_text(text: str, size: int = CHUNK_SIZE_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """Naive fixed-size chunking with overlap. Good enough for v1 —
    swap for paragraph-aware chunking later without touching anything
    that calls this function."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks


class RetrievalIndex:
    """One index per paper. Holds every source's chunks and their
    embeddings, and answers 'what's relevant to this query' with
    enough provenance to build a citation."""

    def __init__(self, embedding_dim: int):
        self.embedding_dim = embedding_dim
        self.index = faiss.IndexFlatL2(embedding_dim)
        # Parallel list: index position i in FAISS <-> chunk_registry[i]
        self.chunk_registry: list[SourceChunk] = []
        self.chunk_to_source: dict[str, str] = {}  # chunk_id -> source_id
        self.chunk_by_id: dict[str, SourceChunk] = {}

    def add_source(self, source: Source, embed_fn) -> None:
        """embed_fn: Callable[[list[str]], list[list[float]]] —
        injected so tests can pass a fake embedder instead of
        calling a real API."""
        raw_chunks = chunk_text(source.raw_text)
        embeddings = embed_fn(raw_chunks)

        for text, embedding in zip(raw_chunks, embeddings):
            chunk = SourceChunk(chunk_id=str(uuid.uuid4()), text=text, embedding=embedding)
            source.chunks.append(chunk)
            self.chunk_registry.append(chunk)
            self.chunk_to_source[chunk.chunk_id] = source.id
            self.chunk_by_id[chunk.chunk_id] = chunk

        vectors = np.array(embeddings, dtype="float32")
        self.index.add(vectors)

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        """Returns passages with enough provenance to cite:
        [{chunk_id, source_id, text, distance}, ...]"""
        query_vec = np.array([query_embedding], dtype="float32")
        distances, indices = self.index.search(query_vec, top_k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue  # FAISS pads with -1 if fewer than top_k exist
            chunk = self.chunk_registry[idx]
            results.append({
                "chunk_id": chunk.chunk_id,
                "source_id": self.chunk_to_source[chunk.chunk_id],
                "text": chunk.text,
                "distance": float(dist),
            })
        return results