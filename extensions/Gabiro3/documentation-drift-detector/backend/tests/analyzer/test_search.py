"""Global search across every stored document.

SuperDocs has no search endpoint — the live OpenAPI spec has no search path
and no mention of semantic search or similarity. Retrieval is this system's
job (spec §1), so search is built on the pgvector index that already exists.

The ranking rule these tests pin down: a chunk containing the query always
outranks one that merely resembles it. Someone who typed a word is looking for
that word, and a similarity score must never be able to bury it.
"""

import pytest

from agents.analyzer import search as search_module
from agents.analyzer.search import EXACT_BASE, SEMANTIC_CEILING, Searcher


class FakeLLM:
    """Embeds without a network call. Raises on demand to prove search still
    works when no embedding provider is available."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    async def embed(self, text: str):
        self.calls += 1
        if self.fail:
            raise RuntimeError("no embedding deployment configured")
        return [0.1] * 1536


def row(chunk_id, text, filename="guide.md", doc="d-1", similarity=None, rid="c-1"):
    r = {
        "id": rid,
        "chunk_id": chunk_id,
        "text_content": text,
        "document_id": doc,
        "filename": filename,
        "run_id": "r-1",
    }
    if similarity is not None:
        r["similarity"] = similarity
    return r


def install_db(monkeypatch, exact_rows, semantic_rows=None):
    """Route the two queries in Searcher.search to canned result sets."""
    captured: dict = {}

    async def fake_exec(sql, values=None):
        if "ILIKE" in sql:
            captured["exact"] = (sql, values)
            return exact_rows
        captured["semantic"] = (sql, values)
        return semantic_rows or []

    monkeypatch.setattr("core.db.exec", fake_exec)
    monkeypatch.setattr("agents.analyzer.embedder.to_pgvector", lambda v: "[0.1]")
    return captured


class TestExactMatching:
    @pytest.mark.asyncio
    async def test_finds_the_word_the_user_typed(self, monkeypatch):
        install_db(monkeypatch, [row("c1", "Run npm install to begin")])
        out = await Searcher(FakeLLM()).search("npm install", semantic=False)

        assert out["exact_count"] == 1
        hit = out["results"][0]
        assert hit["match_type"] == "exact"
        assert hit["chunk_id"] == "c1"
        assert hit["filename"] == "guide.md"

    @pytest.mark.asyncio
    async def test_snippet_offsets_land_on_the_match(self, monkeypatch):
        install_db(monkeypatch, [row("c1", "Before the term. Run npm install now. After.")])
        out = await Searcher(FakeLLM()).search("npm install", semantic=False)

        snip = out["results"][0]["snippet"]
        text, start, length = snip["text"], snip["match_start"], snip["match_length"]
        assert text[start:start + length].lower() == "npm install"

    @pytest.mark.asyncio
    async def test_counts_every_occurrence(self, monkeypatch):
        install_db(monkeypatch, [row("c1", "npm and npm and npm")])
        out = await Searcher(FakeLLM()).search("npm", semantic=False)
        assert out["results"][0]["occurrences"] == 3

    @pytest.mark.asyncio
    async def test_whole_word_hit_outranks_an_incidental_substring(self, monkeypatch):
        """Searching 'npm' should put the line that says npm above one that
        only contains it inside 'pnpm'."""
        install_db(monkeypatch, [
            row("c1", "use pnpm for everything", rid="c-1"),
            row("c2", "run npm install", rid="c-2"),
        ])
        out = await Searcher(FakeLLM()).search("npm", semantic=False)
        assert out["results"][0]["chunk_id"] == "c2"

    @pytest.mark.asyncio
    async def test_matching_is_case_insensitive(self, monkeypatch):
        install_db(monkeypatch, [row("c1", "Install NPM now")])
        out = await Searcher(FakeLLM()).search("npm", semantic=False)
        assert out["results"][0]["occurrences"] == 1

    @pytest.mark.asyncio
    async def test_empty_query_searches_nothing(self, monkeypatch):
        install_db(monkeypatch, [row("c1", "anything")])
        out = await Searcher(FakeLLM()).search("   ")
        assert out["results"] == []


class TestSemanticMatching:
    @pytest.mark.asyncio
    async def test_returns_neighbours_labelled_as_related(self, monkeypatch):
        install_db(monkeypatch, [], [row("c9", "package manager setup", similarity=0.88)])
        out = await Searcher(FakeLLM()).search("dependency tooling")

        assert out["semantic_count"] == 1
        hit = out["results"][0]
        assert hit["match_type"] == "semantic"
        assert hit["similarity"] == 0.88
        # Nothing literal matched, so nothing may be highlighted.
        assert hit["snippet"]["match_start"] == -1

    @pytest.mark.asyncio
    async def test_an_exact_hit_always_outranks_a_semantic_one(self, monkeypatch):
        """A similarity score must never promote a chunk that lacks the word
        above one that contains it — hence the disjoint scoring bands."""
        install_db(
            monkeypatch,
            [row("exact", "npm install", rid="c-exact")],
            [row("near", "package manager", similarity=0.99, rid="c-near")],
        )
        out = await Searcher(FakeLLM()).search("npm")

        assert [r["chunk_id"] for r in out["results"]] == ["exact", "near"]
        assert out["results"][0]["score"] >= EXACT_BASE
        assert out["results"][1]["score"] <= SEMANTIC_CEILING

    @pytest.mark.asyncio
    async def test_a_chunk_is_never_listed_twice(self, monkeypatch):
        """The same chunk can satisfy both queries; it is one result."""
        install_db(
            monkeypatch,
            [row("c1", "npm install", rid="same")],
            [row("c1", "npm install", similarity=0.95, rid="same")],
        )
        out = await Searcher(FakeLLM()).search("npm")

        assert len(out["results"]) == 1
        assert out["results"][0]["match_type"] == "exact"

    @pytest.mark.asyncio
    async def test_weak_neighbours_are_excluded_by_the_floor(self, monkeypatch):
        """Cosine similarity always returns something. Without a floor, a
        nonsense query would still fill a page with confident-looking hits."""
        captured = install_db(monkeypatch, [], [])
        await Searcher(FakeLLM()).search("anything")
        assert captured["semantic"][1]["floor"] == search_module.MIN_SEMANTIC_SIMILARITY

    @pytest.mark.asyncio
    async def test_search_survives_an_unavailable_embedding_provider(self, monkeypatch):
        """The literal half needs no model, so a missing deployment must
        degrade search rather than break it."""
        install_db(monkeypatch, [row("c1", "npm install")])
        out = await Searcher(FakeLLM(fail=True)).search("npm")

        assert out["exact_count"] == 1
        assert out["semantic_available"] is False

    @pytest.mark.asyncio
    async def test_reports_when_semantic_results_were_possible(self, monkeypatch):
        install_db(monkeypatch, [row("c1", "npm install")])
        out = await Searcher(FakeLLM()).search("npm")
        assert out["semantic_available"] is True


class TestScope:
    @pytest.mark.asyncio
    async def test_searches_every_document_by_default(self, monkeypatch):
        # The scope predicate, not the selected column of the same name.
        captured = install_db(monkeypatch, [])
        await Searcher(FakeLLM()).search("npm")
        assert "AND d.run_id" not in captured["exact"][0]
        assert "rid" not in captured["exact"][1]

    @pytest.mark.asyncio
    async def test_can_be_narrowed_to_one_run(self, monkeypatch):
        captured = install_db(monkeypatch, [])
        await Searcher(FakeLLM()).search("npm", run_id="r-9")
        assert "AND d.run_id" in captured["exact"][0]
        assert captured["exact"][1]["rid"] == "r-9"

    @pytest.mark.asyncio
    async def test_results_carry_where_they_were_found(self, monkeypatch):
        """A hit is only useful if the UI can open the document at that chunk."""
        install_db(monkeypatch, [row("c7", "npm install", filename="setup.md", doc="doc-42")])
        hit = (await Searcher(FakeLLM()).search("npm", semantic=False))["results"][0]

        assert hit["document_id"] == "doc-42"
        assert hit["filename"] == "setup.md"
        assert hit["chunk_id"] == "c7"

    @pytest.mark.asyncio
    async def test_limit_caps_the_result_list(self, monkeypatch):
        install_db(monkeypatch, [row(f"c{i}", "npm install", rid=f"c-{i}") for i in range(10)])
        out = await Searcher(FakeLLM()).search("npm", limit=3, semantic=False)
        assert len(out["results"]) == 3
