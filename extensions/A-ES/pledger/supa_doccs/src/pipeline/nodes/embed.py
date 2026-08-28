"""Embed node — generates vector embeddings for chunks and stores in pgvector.

This is the final node of the Understand Stage. It takes all chunks from the
pipeline state, generates vector embeddings via an embedding service, and stores
them in a pgvector-enabled table linked to the document_version_id.

All embeddings are generated and stored as a single atomic batch. If any part
fails, all partial results are discarded.
"""

from __future__ import annotations

from typing import Optional, Protocol

from src.pipeline.state import PipelineState


class EmbeddingService(Protocol):
    """Protocol for generating vector embeddings from text."""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (one per input text), where each
            vector is a list of floats.

        Raises:
            Exception: If the embedding API call fails for any reason.
        """
        ...


class VectorStore(Protocol):
    """Protocol for storing embedding vectors in pgvector."""

    async def store_embeddings(
        self, document_version_id: str, embeddings: list[tuple[int, list[float]]]
    ) -> None:
        """Store embeddings linked to a document version.

        Args:
            document_version_id: The UUID string of the document version.
            embeddings: List of (chunk_index, vector) tuples to store.

        Raises:
            Exception: If the storage operation fails for any reason.
        """
        ...


async def embed(
    state: PipelineState,
    *,
    embedding_service: Optional[EmbeddingService] = None,
    vector_store: Optional[VectorStore] = None,
) -> PipelineState:
    """Generate vector embeddings for all chunks and store in pgvector.

    Processes all chunks in a single atomic batch. On success, sets
    embeddings_stored=True. On any failure (embedding API or storage),
    discards all partial results and returns a transient error.

    Args:
        state: The current pipeline state containing chunks,
            document_version_id, and config.
        embedding_service: Optional embedding service implementation.
            If None, the node cannot proceed and returns a transient error.
        vector_store: Optional vector store implementation.
            If None, the node cannot proceed and returns a transient error.

    Returns:
        Updated PipelineState with embeddings_stored, current_node,
        node_status, and completed_nodes set appropriately.
    """
    chunks = state.get("chunks", [])
    document_version_id = state["document_version_id"]

    # Validate dependencies are provided
    if embedding_service is None or vector_store is None:
        return _error_state(
            state,
            error_detail="Embedding service or vector store not provided",
        )

    # Extract texts from chunks for embedding
    texts = [chunk["text"] for chunk in chunks]

    # Generate embeddings for all chunks in a single batch
    try:
        vectors = await embedding_service.embed_batch(texts)
    except Exception as exc:
        return _error_state(
            state,
            error_detail=f"Embedding API failure: {exc}",
        )

    # Pair each chunk index with its embedding vector
    indexed_embeddings: list[tuple[int, list[float]]] = [
        (chunk["index"], vector) for chunk, vector in zip(chunks, vectors)
    ]

    # Store all embeddings atomically
    try:
        await vector_store.store_embeddings(document_version_id, indexed_embeddings)
    except Exception as exc:
        # Discard all partial results — the vector store should handle
        # rollback internally, but we report failure regardless
        return _error_state(
            state,
            error_detail=f"Vector store failure: {exc}",
        )

    # Success — all embeddings stored
    completed_nodes = list(state.get("completed_nodes", []))
    completed_nodes.append("embed")

    return PipelineState(
        **{
            **state,
            "embeddings_stored": True,
            "current_node": "embed",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed_nodes,
        }
    )


def _error_state(state: PipelineState, *, error_detail: str) -> PipelineState:
    """Return a transient error state for the embed node.

    All embed errors are transient — embedding API failures and vector store
    failures are retryable.
    """
    return PipelineState(
        **{
            **state,
            "embeddings_stored": False,
            "current_node": "embed",
            "node_status": "error",
            "error_type": "transient",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )
