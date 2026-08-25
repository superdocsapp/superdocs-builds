from abc import ABC, abstractmethod
from typing import List


class EmbeddingProvider(ABC):
    """Provider-agnostic interface for text embedding."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        ...

    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of texts.

        Returns a list of float vectors, one per input text.
        Raises RuntimeError with an actionable message if the provider
        is unavailable (missing library, missing model, etc.).
        """
        ...

    async def embed_one(self, text: str) -> List[float]:
        """Convenience wrapper: embed a single text."""
        results = await self.embed([text])
        return results[0]
