import asyncio
from typing import List

from backend.core.retrieval.provider import EmbeddingProvider


class SentenceTransformerProvider(EmbeddingProvider):
    """
    Embedding provider backed by sentence-transformers all-MiniLM-L6-v2.

    Fails clearly at construction time if sentence-transformers is unavailable.
    """

    MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
    DIMENSION = 384

    def __init__(self, model_name: str = MODEL_NAME):
        try:
            from sentence_transformers import SentenceTransformer
        except (ImportError, TypeError):
            raise RuntimeError(
                "sentence-transformers is not installed or not importable. "
                "Run: pip install sentence-transformers  "
                "or add it to pyproject.toml dependencies."
            )
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Embed texts using the loaded model.

        Runs synchronous SentenceTransformer.encode in a thread executor
        so it does not block the asyncio event loop.
        """
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(
            None,
            lambda: self._model.encode(texts, normalize_embeddings=True).tolist()
        )
        return vectors
