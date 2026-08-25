"""
@file: backend/services/vector_store.py
@description: Embeddings and pgvector operations. Two backends: a local
    sentence-transformers model for real runs, and a deterministic hash embedder for
    tests so CI never downloads model weights or needs network. Also owns cosine
    similarity search used for clustering conversations and matching this quarter's
    themes to last quarter's by meaning rather than by name.
@flow: get_embedder() returns a cached embedder honouring settings.embedding_backend ->
    embed_texts() produces unit-normalised vectors -> stored on Conversation.embedding /
    Theme.embedding -> find_similar_themes() runs a pgvector cosine search to match
    across quarters.
@dependencies:
    - pgvector: cosine_distance operator for SQL-side similarity
    - sentence_transformers (optional): local embedding model
"""

from __future__ import annotations

import hashlib
import logging
import math
import uuid
from abc import ABC, abstractmethod
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models import Conversation, Theme

logger = logging.getLogger(__name__)


class Embedder(ABC):
    """Produces unit-normalised vectors of settings.embedding_dim length."""

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class HashEmbedder(Embedder):
    """Deterministic, dependency-free embedder for tests.

    Not semantically meaningful in the way a trained model is, but it is stable, fast,
    and gives near-identical text similar vectors via character-trigram hashing — enough
    for clustering and matching assertions to be exercised without network access.
    """

    def __init__(self, dimension: int | None = None) -> None:
        self._dim = dimension or settings.embedding_dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        normalised = " ".join(text.lower().split())
        if not normalised:
            # A zero vector breaks cosine distance; use a stable unit basis instead.
            vector[0] = 1.0
            return vector

        # Character trigrams so near-identical strings land near each other.
        tokens = [normalised[i : i + 3] for i in range(max(len(normalised) - 2, 1))]
        tokens += normalised.split()
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]


class LocalEmbedder(Embedder):
    """sentence-transformers embedder. Loaded lazily so imports stay cheap."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or settings.embedding_model
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import

            logger.info("Loading embedding model %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def dimension(self) -> int:
        return int(self._ensure_model().get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        vectors = model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return [list(map(float, v)) for v in vectors]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Return the configured embedder, falling back to hash if the model won't load."""
    if settings.embedding_backend == "hash":
        return HashEmbedder()
    try:
        embedder = LocalEmbedder()
        dim = embedder.dimension
        if dim != settings.embedding_dim:
            # A dimension mismatch would fail at INSERT with an opaque pgvector error.
            # Fail here instead, with the fix spelled out.
            raise ValueError(
                f"Model {settings.embedding_model} emits {dim}-dim vectors but "
                f"EMBEDDING_DIM is {settings.embedding_dim}. Set EMBEDDING_DIM={dim} "
                f"and re-run migrations."
            )
        return embedder
    except ImportError:
        logger.warning(
            "sentence-transformers not installed; falling back to hash embedder. "
            "Theme matching will be weaker."
        )
        return HashEmbedder()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def centroid(vectors: list[list[float]]) -> list[float] | None:
    """Mean vector, unit-normalised. Used as a theme's position in embedding space."""
    if not vectors:
        return None
    dim = len(vectors[0])
    acc = [0.0] * dim
    for vec in vectors:
        for i, val in enumerate(vec):
            acc[i] += val
    norm = math.sqrt(sum(v * v for v in acc))
    if norm == 0.0:
        return None
    return [v / norm for v in acc]


async def embed_conversations(
    session: AsyncSession, run_id: uuid.UUID, batch_size: int = 64
) -> int:
    """Embed every conversation in a run that lacks a vector. Returns count embedded."""
    embedder = get_embedder()
    stmt = select(Conversation).where(
        Conversation.run_id == run_id, Conversation.embedding.is_(None)
    )
    rows = list((await session.execute(stmt)).scalars())
    if not rows:
        return 0

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        vectors = embedder.embed([c.raw_text[: settings.max_conversation_chars] for c in batch])
        for conv, vec in zip(batch, vectors):
            conv.embedding = vec
    await session.flush()
    logger.info("Embedded %d conversations for run %s", len(rows), run_id)
    return len(rows)


async def find_similar_themes(
    session: AsyncSession,
    run_id: uuid.UUID,
    query_vector: list[float],
    *,
    limit: int = 5,
    min_similarity: float = 0.0,
) -> list[tuple[Theme, float]]:
    """Cosine-nearest themes within one run.

    pgvector's <=> operator is cosine distance, so similarity is 1 - distance. The
    filter runs SQL-side so we never pull every theme into Python to sort it.
    """
    dialect = session.bind.dialect.name if session.bind is not None else ""

    if dialect == "postgresql":
        # Sort and limit in SQL so we never pull every theme into Python.
        distance = Theme.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(Theme, distance)
            .where(Theme.run_id == run_id, Theme.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
        scored = [(theme, 1.0 - float(dist)) for theme, dist in rows]
    else:
        # SQLite stores embeddings as JSON text and has no vector operators, so the
        # comparison happens in Python. Fine for the test-sized data that runs here;
        # Postgres is the path that has to scale.
        stmt = select(Theme).where(
            Theme.run_id == run_id, Theme.embedding.is_not(None)
        )
        themes = list((await session.execute(stmt)).scalars())
        scored = [
            (theme, cosine_similarity(query_vector, list(theme.embedding)))
            for theme in themes
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        scored = scored[:limit]

    return [(t, sim) for t, sim in scored if sim >= min_similarity]


def match_prior_themes(
    current: list[tuple[str, list[float]]],
    prior: list[tuple[str, list[float], int]],
    *,
    threshold: float = 0.60,
) -> dict[str, tuple[str, int, float]]:
    """Greedy one-to-one match of current themes to prior-quarter themes.

    Greedy on descending similarity so the strongest pair claims each side first; a
    prior theme is consumed once matched, which prevents two current themes both
    claiming the same prior volume and double-counting the comparison.

    Returns {current_name: (prior_name, prior_count, similarity)}.
    """
    pairs: list[tuple[float, str, str, int]] = []
    for cur_name, cur_vec in current:
        for pri_name, pri_vec, pri_count in prior:
            sim = cosine_similarity(cur_vec, pri_vec)
            if sim >= threshold:
                pairs.append((sim, cur_name, pri_name, pri_count))

    pairs.sort(key=lambda p: p[0], reverse=True)
    matched: dict[str, tuple[str, int, float]] = {}
    used_prior: set[str] = set()
    for sim, cur_name, pri_name, pri_count in pairs:
        if cur_name in matched or pri_name in used_prior:
            continue
        matched[cur_name] = (pri_name, pri_count, sim)
        used_prior.add(pri_name)
    return matched
