"""Provider-independent local embeddings for semantic candidate retrieval."""
from __future__ import annotations

import hashlib
import math
import re

EMBEDDING_DIMENSIONS = 384


class HashEmbeddingProvider:
    """Deterministic feature-hashing embedding with no external data transfer."""

    dimensions = EMBEDDING_DIMENSIONS

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[\w'-]+", text.casefold())
        for token in tokens:
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]
