"""
Pluggable embedding providers for `PriorPetition.semantic_matches`.

The original semantic tier used TF-IDF + cosine similarity directly --
honest about its real limitation (documented at length in `rfe.py`): it
requires literal shared tokens between two texts, so it cannot connect
true zero-overlap synonyms like "expertise" and "experience". A real
embeddings model (one trained to place synonymous phrases near each
other in vector space regardless of shared tokens) is what closes that
gap.

This module defines a small `EmbeddingProvider` interface and two
implementations:

- `TfidfEmbeddingProvider`: wraps the exact same TF-IDF + cosine logic
  that lived directly in `rfe.py` before this module existed. Zero
  dependencies beyond scikit-learn (already used), zero network calls,
  zero API cost -- and still the correct fallback default, so nothing
  about the previous default behavior changes unless a real provider is
  explicitly configured.
- `APIEmbeddingProvider`: calls a configurable OpenAI-compatible
  `/v1/embeddings` endpoint (works with OpenAI directly, and with the
  many providers -- including self-hosted -- that implement the same
  request/response shape) and computes cosine similarity over the
  returned vectors. Includes an in-memory cache keyed by text hash (a
  petition's argument texts are embedded once and reused across every
  RFE item's semantic-match lookup in a single run, rather than
  re-embedding the same text repeatedly) and the same retry/backoff
  policy used everywhere else in this package.

Provider selection: `get_default_provider()` returns an
`APIEmbeddingProvider` if `EMBEDDINGS_API_KEY` is set in the environment,
otherwise `TfidfEmbeddingProvider` -- so this is opt-in. This sandbox has
no network access to a real embeddings endpoint to test against, so
`APIEmbeddingProvider` is tested here with a mocked HTTP layer
(`requests_mock`), exactly like `SuperDocsClient` is tested -- the code
path is real and production-ready, it just can't be exercised against a
live API from within this development environment.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger("rfe_response_builder.embeddings")

DEFAULT_EMBEDDINGS_BASE_URL = os.environ.get("EMBEDDINGS_BASE_URL", "https://api.openai.com/v1")
DEFAULT_EMBEDDINGS_MODEL = os.environ.get("EMBEDDINGS_MODEL", "text-embedding-3-small")

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class EmbeddingProviderError(RuntimeError):
    pass


class EmbeddingProvider(ABC):
    """Minimal interface `PriorPetition.semantic_matches` depends on --
    embed a batch of texts, get back one similarity score per (query,
    candidate) pair. Kept deliberately narrow so swapping providers
    never requires touching `rfe.py`."""

    @abstractmethod
    def similarities(self, query: str, candidates: list[str]) -> list[float]:
        """Returns one similarity score in [0, 1] (well-behaved
        implementations; not strictly enforced) per entry in
        `candidates`, in the same order. Must return `[]` for empty
        `candidates` rather than raising."""
        raise NotImplementedError


class TfidfEmbeddingProvider(EmbeddingProvider):
    """The original behavior, unchanged: TF-IDF + cosine similarity via
    scikit-learn. See this module's docstring and `rfe.py`'s
    `semantic_matches` docstring for the honest limitation (requires
    literal shared tokens; does not connect true synonyms)."""

    def similarities(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            logger.warning("scikit-learn is not installed -- TfidfEmbeddingProvider returning all-zero similarities.")
            return [0.0] * len(candidates)

        corpus = list(candidates) + [query]
        try:
            vectorizer = TfidfVectorizer(stop_words="english")
            matrix = vectorizer.fit_transform(corpus)
        except ValueError:
            return [0.0] * len(candidates)

        query_vec = matrix[-1]
        candidate_vecs = matrix[:-1]
        sims = cosine_similarity(query_vec, candidate_vecs)[0]
        return [float(s) for s in sims]


class APIEmbeddingProvider(EmbeddingProvider):
    """Calls a configurable OpenAI-compatible `/v1/embeddings` endpoint.
    Embeds `query` and every entry in `candidates` (using the in-memory
    cache to skip re-embedding text already seen this process lifetime --
    a petition's argument texts get looked up once per RFE item in a
    single run, so this avoids N redundant embedding calls for the same
    N argument texts), then computes cosine similarity in pure Python
    (no numpy/sklearn dependency needed for this path).

    Transient failures (429/5xx) retry with exponential backoff, same
    policy as `SuperDocsClient`. A persistent failure raises
    `EmbeddingProviderError` -- the caller (`semantic_matches`) is
    expected to catch this and degrade to returning no semantic matches
    for that lookup, exactly as it already does for a missing
    scikit-learn install, rather than let an embeddings-provider outage
    break the whole matching pipeline."""

    def __init__(self, api_key: str, base_url: str = DEFAULT_EMBEDDINGS_BASE_URL,
                 model: str = DEFAULT_EMBEDDINGS_MODEL, session: requests.Session | None = None,
                 max_retries: int = 2, retry_backoff_s: float = 1.0, timeout_s: float = 30.0):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.http = session or requests.Session()
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s
        self.timeout_s = timeout_s
        self._cache: dict[str, list[float]] = {}

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        uncached = [t for t in texts if t not in self._cache]
        if uncached:
            vectors = self._request_embeddings(uncached)
            for text, vec in zip(uncached, vectors):
                self._cache[text] = vec
        return [self._cache[t] for t in texts]

    def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        attempt = 0
        while True:
            resp = self.http.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "input": texts},
                timeout=self.timeout_s,
            )
            if resp.status_code >= 400:
                retryable = resp.status_code in _RETRYABLE_STATUS_CODES
                if not retryable or attempt >= self.max_retries:
                    raise EmbeddingProviderError(f"embeddings API error {resp.status_code}: {resp.text[:500]}")
                delay = self.retry_backoff_s * (2 ** attempt)
                logger.warning("embeddings API call failed (status=%s, attempt=%d/%d); retrying in %.1fs",
                               resp.status_code, attempt + 1, self.max_retries, delay)
                time.sleep(delay)
                attempt += 1
                continue
            data = resp.json()
            # Sort by index -- OpenAI-compatible APIs return results in
            # the order requested, but this is defensive against
            # implementations that don't guarantee it.
            ordered = sorted(data["data"], key=lambda d: d.get("index", 0))
            return [item["embedding"] for item in ordered]

    def similarities(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        try:
            all_vecs = self._embed_batch([query] + list(candidates))
        except (requests.RequestException, EmbeddingProviderError, KeyError) as e:
            logger.error("embeddings provider failed, returning no semantic matches for this lookup: %s", e)
            return [0.0] * len(candidates)

        query_vec, candidate_vecs = all_vecs[0], all_vecs[1:]
        return [_cosine_similarity(query_vec, vec) for vec in candidate_vecs]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_default_provider() -> EmbeddingProvider:
    """Opt-in real embeddings: returns `APIEmbeddingProvider` if
    `EMBEDDINGS_API_KEY` is set, otherwise the zero-cost, zero-network
    `TfidfEmbeddingProvider` -- unchanged default behavior unless a real
    provider is explicitly configured."""
    api_key = os.environ.get("EMBEDDINGS_API_KEY")
    if api_key:
        return APIEmbeddingProvider(api_key=api_key)
    return TfidfEmbeddingProvider()
