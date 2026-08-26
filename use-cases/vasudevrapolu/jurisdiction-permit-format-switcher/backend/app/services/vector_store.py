"""Small retrieval boundary.

Production PostgreSQL deployments can enable pgvector and store a fixed-width embedding per
source chunk. The deterministic demo uses lexical retrieval so tests never need a live model.
"""
from math import sqrt

def hash_embedding(text: str, dims: int = 16) -> list[float]:
    values=[0.0]*dims
    for token in text.lower().split():
        values[hash(token)%dims]+=1.0
    norm=sqrt(sum(x*x for x in values)) or 1.0
    return [x/norm for x in values]

def cosine(a: list[float], b: list[float]) -> float:
    return sum(x*y for x,y in zip(a,b))

def lexical_vector_search(chunks: list[dict], query: str, top_k: int = 5) -> list[dict]:
    q=hash_embedding(query)
    ranked=sorted(chunks,key=lambda c:cosine(q,hash_embedding(c.get("text", ""))),reverse=True)
    return ranked[:top_k]
