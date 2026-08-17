import pytest

from agents.analyzer.embedder import to_pgvector


class TestToPgvector:
    """The embedding is a bound parameter, so it must be bare pgvector text.

    Wrapping it in quotes or appending ::vector made Postgres reject every
    write with 'Vector contents must start with "["' — which silently left
    every chunk unembedded and made retrieval rank on NULL similarity.
    """

    def test_renders_bracketed_list(self):
        assert to_pgvector([1.0, 2.0, 3.0]) == "[1.0,2.0,3.0]"

    def test_has_no_surrounding_quotes(self):
        out = to_pgvector([0.1, 0.2])
        assert not out.startswith("'") and not out.endswith("'")

    def test_has_no_inline_cast(self):
        assert "::vector" not in to_pgvector([0.1, 0.2])

    def test_starts_with_bracket(self):
        # Exactly what Postgres complains about when it is missing.
        assert to_pgvector([0.0] * 4).startswith("[")

    def test_coerces_ints_to_float(self):
        assert to_pgvector([1, 2]) == "[1.0,2.0]"

    def test_empty_vector(self):
        assert to_pgvector([]) == "[]"

    def test_roundtrips_dimension(self):
        vec = [0.0] * 1536
        assert to_pgvector(vec).count(",") == 1535


class TestDimensionGuard:
    """Swapping to a wider embedding model breaks every insert against a
    vector(1536) column, and pgvector's own error names neither the model nor
    the column."""

    def test_accepts_matching_width(self):
        from agents.analyzer.embedder import check_dimensions

        check_dimensions([0.0] * 1536, expected=1536)  # must not raise

    def test_rejects_wider_model(self):
        from agents.analyzer.embedder import (
            EmbeddingDimensionMismatch,
            check_dimensions,
        )

        with pytest.raises(EmbeddingDimensionMismatch) as exc:
            check_dimensions([0.0] * 3072, expected=1536)
        msg = str(exc.value)
        assert "3072" in msg and "1536" in msg
        # Names both remedies.
        assert "text-embedding-3-small" in msg
        assert "DRIFT_EMBEDDING_DIM" in msg

    def test_rejects_narrower_model(self):
        from agents.analyzer.embedder import (
            EmbeddingDimensionMismatch,
            check_dimensions,
        )

        with pytest.raises(EmbeddingDimensionMismatch):
            check_dimensions([0.0] * 768, expected=1536)
