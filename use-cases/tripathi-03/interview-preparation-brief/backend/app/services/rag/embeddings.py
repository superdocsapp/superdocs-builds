"""Embedding clients: OpenAI, Gemini, or free local hashing (no API key)."""

from __future__ import annotations

import hashlib
import math
import re

from app.core.config import get_settings
from app.core.exceptions import AppError, LLMConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9_+#./-]{2,}", re.IGNORECASE)


def local_hash_embed(text: str, dimensions: int) -> list[float]:
    """Deterministic feature-hashing embedding — free, offline, no API."""
    vector = [0.0] * dimensions
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        tokens = ["empty"]

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (digest[5] / 255.0)
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class EmbeddingService:
    """Generate vector embeddings for RAG chunks and queries."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = self.settings.embedding_provider
        self._openai = None
        self._gemini_model = None

        if self.provider == "openai":
            if not self.settings.openai_api_key:
                raise LLMConfigurationError(
                    "OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai."
                )
            from openai import AsyncOpenAI

            self._openai = AsyncOpenAI(api_key=self.settings.openai_api_key)
        elif self.provider == "gemini":
            if not self.settings.gemini_api_key:
                raise LLMConfigurationError(
                    "GEMINI_API_KEY is required when EMBEDDING_PROVIDER=gemini."
                )
        elif self.provider == "local":
            logger.info(
                "Using free local embeddings (%s dims)",
                self.settings.embedding_dimensions,
            )
        else:
            raise LLMConfigurationError(
                f"Unsupported EMBEDDING_PROVIDER={self.provider!r}. "
                "Use: local, openai, or gemini."
            )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        if self.provider == "local":
            dims = self.settings.embedding_dimensions
            return [local_hash_embed(text, dims) for text in texts]

        if self.provider == "gemini":
            return await self._embed_gemini(texts)

        return await self._embed_openai(texts)

    async def embed_query(self, query: str) -> list[float]:
        vectors = await self.embed_texts([query])
        return vectors[0]

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        from openai import APIError, AuthenticationError, RateLimitError

        assert self._openai is not None
        vectors: list[list[float]] = []
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                response = await self._openai.embeddings.create(
                    model=self.settings.embedding_model,
                    input=batch,
                )
            except RateLimitError as exc:
                message = str(exc)
                if any(token in message.lower() for token in ("credit", "quota", "billing")):
                    raise AppError(
                        "OpenAI has no credits remaining. Switch EMBEDDING_PROVIDER=local "
                        "in .env (free) or add billing credits."
                    ) from exc
                raise AppError(
                    "OpenAI rate limit hit while creating embeddings. Wait and retry."
                ) from exc
            except AuthenticationError as exc:
                raise LLMConfigurationError(
                    "OpenAI API key is invalid. Check OPENAI_API_KEY in .env."
                ) from exc
            except APIError as exc:
                raise AppError(f"OpenAI embeddings failed: {exc.message or exc}") from exc
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend([item.embedding for item in ordered])
        return vectors

    async def _embed_gemini(self, texts: list[str]) -> list[list[float]]:
        try:
            from google import genai
        except ImportError as exc:
            raise LLMConfigurationError(
                "google-genai is required for Gemini embeddings. "
                "Run: pip install google-genai"
            ) from exc

        client = genai.Client(api_key=self.settings.gemini_api_key)
        model = self.settings.embedding_model or "text-embedding-004"
        vectors: list[list[float]] = []
        dims = self.settings.embedding_dimensions

        for text in texts:
            try:
                result = client.models.embed_content(
                    model=model,
                    contents=text,
                )
            except Exception as exc:  # noqa: BLE001
                raise AppError(f"Gemini embeddings failed: {exc}") from exc

            embedding = list(result.embeddings[0].values)
            if len(embedding) < dims:
                embedding = embedding + [0.0] * (dims - len(embedding))
            elif len(embedding) > dims:
                embedding = embedding[:dims]
            vectors.append(embedding)
        return vectors
