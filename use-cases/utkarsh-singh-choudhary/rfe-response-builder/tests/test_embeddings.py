"""Tests for rfe_response_builder/embeddings.py."""
import requests_mock

from rfe_response_builder.embeddings import (
    APIEmbeddingProvider,
    EmbeddingProviderError,
    TfidfEmbeddingProvider,
    _cosine_similarity,
    get_default_provider,
)


def test_cosine_similarity_identical_vectors_is_one():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_zero_vector_returns_zero_not_nan():
    assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_tfidf_provider_returns_empty_for_no_candidates():
    provider = TfidfEmbeddingProvider()
    assert provider.similarities("some query", []) == []


def test_tfidf_provider_scores_shared_vocabulary_higher():
    provider = TfidfEmbeddingProvider()
    sims = provider.similarities(
        "corporate law practice for a decade",
        ["Corporate law corporate law tax law practice for a decade.", "A recipe for baking sourdough bread."],
    )
    assert sims[0] > sims[1]


def test_get_default_provider_returns_tfidf_when_no_api_key_configured(monkeypatch):
    monkeypatch.delenv("EMBEDDINGS_API_KEY", raising=False)
    provider = get_default_provider()
    assert isinstance(provider, TfidfEmbeddingProvider)


def test_get_default_provider_returns_api_provider_when_key_configured(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_API_KEY", "sk-fake-embeddings-key")
    provider = get_default_provider()
    assert isinstance(provider, APIEmbeddingProvider)


def _mock_embeddings_response(m, vectors_by_text: dict[str, list[float]]):
    def callback(request, context):
        body = request.json()
        texts = body["input"]
        return {"data": [{"index": i, "embedding": vectors_by_text[t]} for i, t in enumerate(texts)]}
    m.post("https://api.openai.com/v1/embeddings", json=callback)


def test_api_provider_connects_true_zero_overlap_synonyms():
    """The core capability TfidfEmbeddingProvider explicitly cannot
    provide: two texts with ZERO shared vocabulary, but that a real
    embeddings model would place close together in vector space (here,
    simulated directly via hand-picked vectors -- the point is that
    APIEmbeddingProvider computes similarity purely from the returned
    vectors, with no token-overlap requirement anywhere in its own code)."""
    provider = APIEmbeddingProvider(api_key="sk-fake", retry_backoff_s=0)
    query = "expertise in aeronautics"
    candidate = "experience building rockets"  # zero shared words with query
    with requests_mock.Mocker() as m:
        _mock_embeddings_response(m, {
            query: [1.0, 0.0, 0.0],
            candidate: [0.95, 0.05, 0.0],  # deliberately near-identical vector despite no shared tokens
        })
        sims = provider.similarities(query, [candidate])
    assert sims[0] > 0.9


def test_api_provider_caches_repeated_texts_within_a_run():
    provider = APIEmbeddingProvider(api_key="sk-fake", retry_backoff_s=0)
    with requests_mock.Mocker() as m:
        _mock_embeddings_response(m, {"a": [1.0, 0.0], "b": [0.0, 1.0]})
        provider.similarities("a", ["b"])
        assert m.call_count == 1
        # Same texts again -- should hit the cache, not make a second HTTP call.
        provider.similarities("a", ["b"])
        assert m.call_count == 1


def test_api_provider_retries_transient_failure_and_recovers():
    provider = APIEmbeddingProvider(api_key="sk-fake", retry_backoff_s=0)
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/embeddings",
            [
                {"status_code": 503, "json": {"error": "temporarily unavailable"}},
                {"status_code": 200, "json": {"data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [1.0, 0.0]},
                ]}},
            ],
        )
        sims = provider.similarities("a", ["b"])
    assert sims == [1.0]
    assert m.call_count == 2


def test_api_provider_returns_zero_scores_instead_of_raising_on_persistent_failure():
    """If the embeddings API is down, semantic_matches must degrade
    gracefully (no semantic matches surfaced) rather than break the whole
    matching pipeline -- proven here at the provider level."""
    provider = APIEmbeddingProvider(api_key="sk-fake", retry_backoff_s=0)
    with requests_mock.Mocker() as m:
        m.post("https://api.openai.com/v1/embeddings", status_code=500, json={"error": "down"})
        sims = provider.similarities("a", ["b", "c"])
    assert sims == [0.0, 0.0]


def test_api_provider_requires_api_key():
    try:
        APIEmbeddingProvider(api_key="")
        assert False, "expected ValueError"
    except ValueError:
        pass
