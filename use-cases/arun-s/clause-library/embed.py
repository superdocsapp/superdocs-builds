"""Deterministic, keyless embedder — a hashing bag-of-words with L2 norm, so semantic
search runs with no model or key and is fully testable. This is the same seam the main
system uses: a neural embedder (OpenAI / a local model) + pgvector drops in behind
`embed` for true synonym matching; the interface never changes.
"""
from __future__ import annotations
import hashlib
import math
import re

DIM = 512


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def embed(text: str) -> list[float]:
    v = [0.0] * DIM
    for tok in _tokens(text):
        v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
