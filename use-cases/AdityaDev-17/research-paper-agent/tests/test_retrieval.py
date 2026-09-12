from src.models import Source
from src.retrieval import RetrievalIndex


def fake_embed_fn(texts: list[str]) -> list[list[float]]:
    """Deterministic fake: embedding = [len(text), 0.0, 0.0]
    Good enough to prove distance/ranking plumbing without real embeddings."""
    return [[float(len(t)), 0.0, 0.0] for t in texts]


def test_search_returns_correct_source_provenance():
    index = RetrievalIndex(embedding_dim=3)

    source_a = Source(id="src-a", title="Paper A", raw_text="x" * 50)
    source_b = Source(id="src-b", title="Paper B", raw_text="y" * 2000)

    index.add_source(source_a, fake_embed_fn)
    index.add_source(source_b, fake_embed_fn)

    # Query embedding close to source_a's short chunk
    results = index.search(query_embedding=[50.0, 0.0, 0.0], top_k=2)

    assert len(results) == 2
    assert results[0]["source_id"] == "src-a"
    assert results[0]["distance"] < results[1]["distance"]