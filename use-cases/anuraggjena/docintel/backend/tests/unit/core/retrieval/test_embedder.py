import pytest


def test_sentence_transformer_provider_imports():
    """Provider class is importable."""
    from backend.core.retrieval.sentence_transformer import SentenceTransformerProvider
    assert SentenceTransformerProvider is not None


def test_sentence_transformer_dimension():
    """all-MiniLM-L6-v2 always produces 384-dim vectors."""
    from backend.core.retrieval.sentence_transformer import SentenceTransformerProvider
    p = SentenceTransformerProvider()
    assert p.dimension == 384


@pytest.mark.asyncio
async def test_embed_returns_correct_shape():
    """embed() returns one vector per input text."""
    from backend.core.retrieval.sentence_transformer import SentenceTransformerProvider
    p = SentenceTransformerProvider()
    vecs = await p.embed(["hello world", "tariff classification"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 384
    assert len(vecs[1]) == 384


@pytest.mark.asyncio
async def test_embed_one_returns_single_vector():
    from backend.core.retrieval.sentence_transformer import SentenceTransformerProvider
    p = SentenceTransformerProvider()
    vec = await p.embed_one("HS code 8471.30")
    assert len(vec) == 384


def test_missing_sentence_transformers_raises_runtime_error(monkeypatch):
    """If sentence_transformers is not installed, fail clearly at construction."""
    import sys
    # Hide the module
    original = sys.modules.get("sentence_transformers")
    sys.modules["sentence_transformers"] = None  # type: ignore
    try:
        import importlib
        import backend.core.retrieval.sentence_transformer as mod
        importlib.reload(mod)
        with pytest.raises(RuntimeError, match="sentence-transformers"):
            mod.SentenceTransformerProvider()
    finally:
        if original is not None:
            sys.modules["sentence_transformers"] = original
        else:
            del sys.modules["sentence_transformers"]
        importlib.reload(mod)
