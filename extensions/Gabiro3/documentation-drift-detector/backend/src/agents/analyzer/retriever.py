from uuid import UUID

from core.llm_provider import LLMProvider
from agents.analyzer.embedder import to_pgvector

# Retrieval is recall, not a verdict: nominate generously and let the
# Finder/Verifier decide. Literal matches are weighted at least as heavily
# as vector similarity because renames and default changes (npm -> pnpm,
# 3000 -> 8080) appear verbatim in the docs they contradict.
VECTOR_WEIGHT = 0.5
KEYWORD_WEIGHT = 0.5


class Retriever:
    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self._embed_cache: dict[str, list[float]] = {}

    async def _embed(self, text: str) -> list[float]:
        if text not in self._embed_cache:
            self._embed_cache[text] = await self.llm.embed(text)
        return self._embed_cache[text]

    async def retrieve(
        self, run_id: UUID, change_facts: list, top_k: int = 10
    ) -> list[list[dict]]:
        from core.db import exec

        results = []
        for cf in change_facts:
            query_text = (cf.old_value or cf.new_value or "").strip()
            if not query_text:
                results.append([])
                continue

            emb = to_pgvector(await self._embed(query_text))

            # COALESCE keeps chunks with no embedding in play (they can still
            # win on the keyword leg) instead of NULL-ing the whole score.
            rows = await exec(
                """
                WITH scored AS (
                    SELECT c.id,
                           c.chunk_id,
                           c.html,
                           c.content_hash,
                           COALESCE(
                               1 - (c.embedding <=> CAST(:emb AS vector)), 0
                           ) AS vector_score,
                           CASE WHEN c.html ILIKE :kw THEN 1.0 ELSE 0.0 END
                               AS keyword_score
                      FROM chunks c
                      JOIN documents d ON d.id = c.document_id
                     WHERE d.run_id = :rid
                )
                SELECT id, chunk_id, html, content_hash,
                       vector_score, keyword_score,
                       (vector_score * :vw + keyword_score * :kwx) AS score
                  FROM scored
                 ORDER BY score DESC, keyword_score DESC
                 LIMIT :lim
                """,
                {
                    "emb": emb,
                    "kw": f"%{query_text}%",
                    "rid": str(run_id),
                    "vw": VECTOR_WEIGHT,
                    "kwx": KEYWORD_WEIGHT,
                    "lim": top_k,
                },
            )
            results.append([dict(r) for r in rows])
        return results
