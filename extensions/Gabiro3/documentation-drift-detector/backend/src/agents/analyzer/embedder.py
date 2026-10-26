from uuid import UUID

from core.config import EMBEDDING_DIM
from core.llm_provider import LLMProvider


class EmbeddingDimensionMismatch(RuntimeError):
    """The model's vector width does not match the pgvector column."""


def check_dimensions(vector: list[float], expected: int = EMBEDDING_DIM) -> None:
    """Fail with an explanation rather than a raw pgvector type error.

    Swapping to a wider model (text-embedding-3-large is 3072) silently
    breaks every insert against a vector(1536) column; the native error does
    not say which model or column is at fault.
    """
    if len(vector) != expected:
        raise EmbeddingDimensionMismatch(
            f"Embedding model returned {len(vector)} dimensions but "
            f"chunks.embedding is vector({expected}). Either deploy a "
            f"{expected}-dimension model (text-embedding-3-small, "
            f"text-embedding-ada-002), or widen the column and set "
            f"DRIFT_EMBEDDING_DIM={len(vector)}."
        )


def to_pgvector(values: list[float]) -> str:
    """Render an embedding in pgvector's text form: [1,2,3].

    Note there are no surrounding quotes and no ::vector cast here — those
    belong in the SQL, not in a bound parameter. Embedding them in the value
    makes Postgres reject it with 'Vector contents must start with "["'.
    """
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


class Embedder:
    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self._cache: dict[str, list[float]] = {}

    async def embed_documents(self, document_ids: list[UUID]):
        for doc_id in document_ids:
            await self._embed_chunks(doc_id)

    async def _embed_chunks(self, document_id: UUID):
        from core.db import exec

        # Only chunks without an embedding: unchanged content is a cache hit,
        # so re-running (or resuming) a document costs nothing.
        rows = await exec(
            "SELECT id, chunk_id, content_hash, html FROM chunks "
            "WHERE document_id = :did AND embedding IS NULL",
            {"did": str(document_id)},
        )
        for row in rows:
            cache_key = row["content_hash"]
            if cache_key in self._cache:
                emb = self._cache[cache_key]
            else:
                emb = await self.llm.embed(row["html"])
                check_dimensions(emb)
                self._cache[cache_key] = emb

            await exec(
                "UPDATE chunks SET embedding = CAST(:emb AS vector) WHERE id = :id",
                {"emb": to_pgvector(emb), "id": str(row["id"])},
            )
