from series_bible.application.embeddings import EMBEDDING_DIMENSIONS, HashEmbeddingProvider


def test_embeddings_are_normalized_deterministic_and_fixed_size():
    provider = HashEmbeddingProvider()
    first = provider.embed("Elena eye color blue")
    second = provider.embed("Elena eye color blue")
    assert len(first) == EMBEDDING_DIMENSIONS
    assert first == second
    assert abs(sum(value * value for value in first) - 1) < 1e-6