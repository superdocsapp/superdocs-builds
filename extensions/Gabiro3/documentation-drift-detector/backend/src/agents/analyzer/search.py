"""Global search across every stored document.

SuperDocs has no search endpoint — its API covers parsing, chat-driven
editing, approval and export. Embedding storage and retrieval are explicitly
this system's job (spec §1), and the pieces already exist: `chunks.embedding`
with an ivfflat index, and `LLMProvider.embed()`.

This is the corpus-wide counterpart to `Retriever`, which nominates candidate
chunks for one change fact inside one run. The difference is who is asking:
the Retriever serves the pipeline and optimises recall for a later LLM to
judge, while search serves a person who typed a word and expects to see that
word.

That distinction sets the ranking rule. An exact match always outranks a
semantic one, because a user searching "pnpm" wants the lines containing
"pnpm" — not the paragraph an embedding considers conceptually adjacent.
Semantic hits are still returned, clearly marked, below the literal ones.
"""

import re
from typing import Optional

from core.llm_provider import LLMProvider
from core.text import snippet_around

# Exact hits are pinned above semantic ones by scoring them on disjoint
# bands rather than by weighting, so no similarity score can ever promote a
# chunk that does not contain the query above one that does.
EXACT_BASE = 1000.0
SEMANTIC_CEILING = 100.0

# A semantic neighbour has to be a genuine one. Cosine similarity always
# returns *something*, so without a floor an unrelated corpus would still
# produce a full page of confident-looking results for a nonsense query.
MIN_SEMANTIC_SIMILARITY = 0.72


def _word_boundary_bonus(text: str, query: str) -> float:
    """Reward a whole-word hit over an incidental substring.

    Searching "npm" should rank the line that says "npm install" above one
    that merely contains "pnpm" inside another word.
    """
    if re.search(rf"\b{re.escape(query)}\b", text, re.IGNORECASE):
        return 50.0
    return 0.0


class Searcher:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def search(
        self,
        query: str,
        limit: int = 20,
        run_id: Optional[str] = None,
        semantic: bool = True,
    ) -> dict:
        from core.db import exec

        q = (query or "").strip()
        if not q:
            return {"query": query, "results": [], "exact_count": 0,
                    "semantic_count": 0, "semantic_available": False}

        scope = "AND d.run_id = :rid" if run_id else ""
        params: dict = {"q": f"%{q}%", "lim": max(limit * 3, 30)}
        if run_id:
            params["rid"] = run_id

        # --- Literal matches: what the user actually typed ---
        exact_rows = await exec(
            f"""
            SELECT c.id, c.chunk_id, c.text_content, c.document_id,
                   d.filename, d.run_id
              FROM chunks c
              JOIN documents d ON d.id = c.document_id
             WHERE c.text_content ILIKE :q {scope}
             LIMIT :lim
            """,
            params,
        )

        results: dict[str, dict] = {}
        for row in exact_rows:
            text = row["text_content"] or ""
            position = text.lower().find(q.lower())
            occurrences = text.lower().count(q.lower())
            results[str(row["id"])] = {
                "chunk_row_id": str(row["id"]),
                "chunk_id": row["chunk_id"],
                "document_id": str(row["document_id"]),
                "filename": row["filename"],
                "run_id": str(row["run_id"]),
                "match_type": "exact",
                "occurrences": occurrences,
                "matched_text": text[position:position + len(q)] if position >= 0 else q,
                "snippet": snippet_around(text, position, len(q)),
                # More occurrences means a chunk is more about the term, but
                # the effect is damped so one dense chunk cannot bury an
                # exact whole-word hit elsewhere.
                "score": (
                    EXACT_BASE
                    + _word_boundary_bonus(text, q)
                    + min(occurrences, 5) * 2.0
                ),
            }

        # --- Semantic neighbours: what the user might have meant ---
        semantic_available = False
        if semantic:
            try:
                embedding = await self.llm.embed(q)
                semantic_available = True
            except Exception:
                # Search must still work when the embedding provider is
                # unconfigured or down; the literal half needs no model at all.
                embedding = None

            if embedding:
                from agents.analyzer.embedder import to_pgvector

                sem_params: dict = {
                    "emb": to_pgvector(embedding),
                    "lim": max(limit * 2, 20),
                    "floor": MIN_SEMANTIC_SIMILARITY,
                }
                if run_id:
                    sem_params["rid"] = run_id

                sem_rows = await exec(
                    f"""
                    SELECT c.id, c.chunk_id, c.text_content, c.document_id,
                           d.filename, d.run_id,
                           1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity
                      FROM chunks c
                      JOIN documents d ON d.id = c.document_id
                     WHERE c.embedding IS NOT NULL {scope}
                       AND 1 - (c.embedding <=> CAST(:emb AS vector)) >= :floor
                     ORDER BY similarity DESC
                     LIMIT :lim
                    """,
                    sem_params,
                )

                for row in sem_rows:
                    key = str(row["id"])
                    if key in results:
                        # Already a literal hit; a similarity score cannot
                        # improve on containing the word.
                        continue
                    text = row["text_content"] or ""
                    similarity = float(row["similarity"])
                    results[key] = {
                        "chunk_row_id": key,
                        "chunk_id": row["chunk_id"],
                        "document_id": str(row["document_id"]),
                        "filename": row["filename"],
                        "run_id": str(row["run_id"]),
                        "match_type": "semantic",
                        "occurrences": 0,
                        "matched_text": None,
                        "similarity": round(similarity, 4),
                        "snippet": snippet_around(text, -1, 0),
                        "score": min(similarity * SEMANTIC_CEILING, SEMANTIC_CEILING),
                    }

        ranked = sorted(results.values(), key=lambda r: -r["score"])[:limit]
        exact_count = sum(1 for r in ranked if r["match_type"] == "exact")

        return {
            "query": q,
            "results": ranked,
            "exact_count": exact_count,
            "semantic_count": len(ranked) - exact_count,
            # Told plainly so the UI can say "no semantic results because no
            # embeddings exist" instead of implying the corpus has no match.
            "semantic_available": semantic_available,
        }
