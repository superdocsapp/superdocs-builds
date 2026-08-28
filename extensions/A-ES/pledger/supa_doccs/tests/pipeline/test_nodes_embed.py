"""Unit tests for the embed node.

Tests cover:
- Successful embedding of all chunks
- Transient error when embedding API fails
- Transient error when vector store fails
- embeddings_stored=True on success, False on failure
- Partial results are discarded on failure (not stored)
- completed_nodes includes "embed" on success
"""

import pytest

from src.pipeline.config import load_config
from src.pipeline.nodes.embed import EmbeddingService, VectorStore, embed
from src.pipeline.state import ChunkEntry, PipelineState, create_initial_state


# --- Mock implementations ---


class MockEmbeddingService:
    """Mock embedding service that returns fixed-dimension vectors."""

    def __init__(
        self,
        *,
        dimension: int = 3,
        should_fail: bool = False,
        fail_message: str = "Embedding API timeout",
    ):
        self.dimension = dimension
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.call_count = 0
        self.last_texts: list[str] = []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        self.last_texts = texts
        if self.should_fail:
            raise RuntimeError(self.fail_message)
        # Return a simple deterministic embedding per text
        return [[float(i)] * self.dimension for i in range(len(texts))]


class MockVectorStore:
    """Mock vector store that records stored embeddings."""

    def __init__(
        self,
        *,
        should_fail: bool = False,
        fail_message: str = "Vector store connection error",
    ):
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.stored: list[tuple[str, list[tuple[int, list[float]]]]] = []
        self.call_count = 0

    async def store_embeddings(
        self, document_version_id: str, embeddings: list[tuple[int, list[float]]]
    ) -> None:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError(self.fail_message)
        self.stored.append((document_version_id, embeddings))


# --- Fixtures ---


@pytest.fixture
def base_state() -> PipelineState:
    """Create a pipeline state with chunks ready for embedding."""
    config = load_config()
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=config,
    )
    state["chunks"] = [
        ChunkEntry(index=0, text="First chunk of text.", start_offset=0, end_offset=20),
        ChunkEntry(index=1, text="Second chunk of text.", start_offset=15, end_offset=36),
        ChunkEntry(index=2, text="Third chunk of text.", start_offset=30, end_offset=50),
    ]
    return state


# --- Tests ---


@pytest.mark.anyio
async def test_successful_embedding(base_state: PipelineState):
    """Test that all chunks are embedded and stored successfully."""
    embedding_service = MockEmbeddingService(dimension=4)
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert result["node_status"] == "completed"
    assert result["embeddings_stored"] is True
    assert result["current_node"] == "embed"
    assert result["error_type"] is None
    assert result["error_detail"] is None

    # Verify the embedding service was called with correct texts
    assert embedding_service.call_count == 1
    assert embedding_service.last_texts == [
        "First chunk of text.",
        "Second chunk of text.",
        "Third chunk of text.",
    ]

    # Verify the vector store was called correctly
    assert vector_store.call_count == 1
    stored_version_id, stored_embeddings = vector_store.stored[0]
    assert stored_version_id == "test-version-id"
    assert len(stored_embeddings) == 3
    assert stored_embeddings[0][0] == 0  # chunk index 0
    assert stored_embeddings[1][0] == 1  # chunk index 1
    assert stored_embeddings[2][0] == 2  # chunk index 2


@pytest.mark.anyio
async def test_completed_nodes_includes_embed(base_state: PipelineState):
    """Test that completed_nodes includes 'embed' on success."""
    embedding_service = MockEmbeddingService()
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert "embed" in result["completed_nodes"]


@pytest.mark.anyio
async def test_completed_nodes_preserves_prior(base_state: PipelineState):
    """Test that embed appends to existing completed_nodes list."""
    base_state["completed_nodes"] = ["ingest", "extract_text", "chunk"]
    embedding_service = MockEmbeddingService()
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert result["completed_nodes"] == ["ingest", "extract_text", "chunk", "embed"]


@pytest.mark.anyio
async def test_transient_error_on_embedding_api_failure(base_state: PipelineState):
    """Test transient error when embedding API fails."""
    embedding_service = MockEmbeddingService(should_fail=True)
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert result["embeddings_stored"] is False
    assert "Embedding API failure" in result["error_detail"]
    assert result["current_node"] == "embed"


@pytest.mark.anyio
async def test_transient_error_on_vector_store_failure(base_state: PipelineState):
    """Test transient error when vector store fails."""
    embedding_service = MockEmbeddingService()
    vector_store = MockVectorStore(should_fail=True)

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert result["embeddings_stored"] is False
    assert "Vector store failure" in result["error_detail"]
    assert result["current_node"] == "embed"


@pytest.mark.anyio
async def test_embeddings_stored_true_on_success(base_state: PipelineState):
    """Test that embeddings_stored is True on successful embedding."""
    embedding_service = MockEmbeddingService()
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert result["embeddings_stored"] is True


@pytest.mark.anyio
async def test_embeddings_stored_false_on_embedding_failure(base_state: PipelineState):
    """Test that embeddings_stored is False when embedding API fails."""
    embedding_service = MockEmbeddingService(should_fail=True)
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert result["embeddings_stored"] is False


@pytest.mark.anyio
async def test_embeddings_stored_false_on_store_failure(base_state: PipelineState):
    """Test that embeddings_stored is False when vector store fails."""
    embedding_service = MockEmbeddingService()
    vector_store = MockVectorStore(should_fail=True)

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert result["embeddings_stored"] is False


@pytest.mark.anyio
async def test_partial_results_discarded_on_store_failure(base_state: PipelineState):
    """Test that partial results are not stored when vector store fails.

    The vector store should not retain any embeddings if it fails mid-write.
    We verify that the store was called but no successful storage occurred.
    """
    vector_store = MockVectorStore(should_fail=True)
    embedding_service = MockEmbeddingService()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    # Embeddings were generated but storage failed
    assert embedding_service.call_count == 1
    # The vector store was called but raised an exception
    assert vector_store.call_count == 1
    # No successful storage occurred
    assert len(vector_store.stored) == 0
    # State reflects failure
    assert result["embeddings_stored"] is False
    assert result["node_status"] == "error"


@pytest.mark.anyio
async def test_partial_results_discarded_on_embedding_failure(
    base_state: PipelineState,
):
    """Test that no embeddings are stored when embedding API fails.

    If embedding generation fails, the vector store should never be called.
    """
    embedding_service = MockEmbeddingService(should_fail=True)
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    # Embedding failed — vector store should not have been called at all
    assert vector_store.call_count == 0
    assert len(vector_store.stored) == 0
    assert result["embeddings_stored"] is False


@pytest.mark.anyio
async def test_embed_not_in_completed_nodes_on_failure(base_state: PipelineState):
    """Test that 'embed' is NOT in completed_nodes on failure."""
    embedding_service = MockEmbeddingService(should_fail=True)
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert "embed" not in result["completed_nodes"]


@pytest.mark.anyio
async def test_error_when_no_services_provided(base_state: PipelineState):
    """Test transient error when neither service is provided."""
    result = await embed(base_state)

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert result["embeddings_stored"] is False
    assert "not provided" in result["error_detail"]


@pytest.mark.anyio
async def test_embed_with_empty_chunks(base_state: PipelineState):
    """Test embedding with empty chunks list still succeeds."""
    base_state["chunks"] = []
    embedding_service = MockEmbeddingService()
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert result["node_status"] == "completed"
    assert result["embeddings_stored"] is True
    assert embedding_service.last_texts == []


@pytest.mark.anyio
async def test_embed_with_single_chunk(base_state: PipelineState):
    """Test embedding with a single chunk."""
    base_state["chunks"] = [
        ChunkEntry(index=0, text="Only one chunk.", start_offset=0, end_offset=15),
    ]
    embedding_service = MockEmbeddingService(dimension=8)
    vector_store = MockVectorStore()

    result = await embed(
        base_state,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    assert result["node_status"] == "completed"
    assert result["embeddings_stored"] is True
    assert embedding_service.last_texts == ["Only one chunk."]

    stored_version_id, stored_embeddings = vector_store.stored[0]
    assert len(stored_embeddings) == 1
    assert stored_embeddings[0][0] == 0  # chunk index
    assert len(stored_embeddings[0][1]) == 8  # embedding dimension
