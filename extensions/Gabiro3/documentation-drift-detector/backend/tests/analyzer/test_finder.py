import pytest

from core.llm_provider import MockLLMProvider
from core.models import ChangeFact
from uuid import uuid4

from agents.analyzer.finder import ChunkVerdict, Finder, FinderOutput


def make_fact(old="npm", new="pnpm"):
    return ChangeFact(
        id=uuid4(), run_id=uuid4(), type="renamed",
        old_value=old, new_value=new, source_ref="CHANGELOG.md",
    )


CANDIDATES = [
    {"chunk_id": "c1", "html": "<p>run npm install</p>"},
    {"chunk_id": "c2", "html": "<p>run npm test</p>"},
    {"chunk_id": "c3", "html": "<p>unrelated prose</p>"},
]


class ScriptedLLM(MockLLMProvider):
    """Returns a fixed set of per-chunk verdicts."""

    def __init__(self, verdicts):
        super().__init__()
        self._verdicts = verdicts

    async def complete(self, prompt, schema, system=""):
        return schema.model_validate({"verdicts": self._verdicts})


class TestPerChunkFindings:
    """Grading is per chunk, so the Finder must answer per chunk. One finding
    per fact made recall unmeasurable: a fact drifted across N chunks could
    never score better than 1/N however well detection worked."""

    @pytest.mark.asyncio
    async def test_emits_one_finding_per_drifted_chunk(self):
        llm = ScriptedLLM([
            {"chunk_id": "c1", "drifted": True, "evidence_quote": "run npm install",
             "proposed_old": "npm install", "proposed_new": "pnpm install", "reason": "stale"},
            {"chunk_id": "c2", "drifted": True, "evidence_quote": "run npm test",
             "proposed_old": "npm test", "proposed_new": "pnpm test", "reason": "stale"},
        ])
        out = await Finder(llm).find_for_fact(make_fact(), CANDIDATES)
        assert len(out) == 2
        assert {f.chunk_id for f in out} == {"c1", "c2"}
        assert all(f.state == "CONFIRMED_DRIFT" for f in out)

    @pytest.mark.asyncio
    async def test_undrifted_chunks_produce_no_finding(self):
        llm = ScriptedLLM([
            {"chunk_id": "c1", "drifted": True, "evidence_quote": "run npm install",
             "proposed_old": "npm", "proposed_new": "pnpm", "reason": "stale"},
            {"chunk_id": "c3", "drifted": False, "reason": "unrelated"},
        ])
        out = await Finder(llm).find_for_fact(make_fact(), CANDIDATES)
        assert [f.chunk_id for f in out] == ["c1"]

    @pytest.mark.asyncio
    async def test_evidence_chunk_id_matches_the_judged_chunk(self):
        llm = ScriptedLLM([
            {"chunk_id": "c2", "drifted": True, "evidence_quote": "run npm test",
             "proposed_old": "npm", "proposed_new": "pnpm", "reason": "stale"},
        ])
        out = await Finder(llm).find_for_fact(make_fact(), CANDIDATES)
        assert out[0].evidence_chunk_id == "c2" == out[0].chunk_id

    @pytest.mark.asyncio
    async def test_verdict_for_unoffered_chunk_is_discarded(self):
        """A verdict about a chunk that was never shown is a fabrication."""
        llm = ScriptedLLM([
            {"chunk_id": "does-not-exist", "drifted": True,
             "evidence_quote": "invented", "reason": "hallucinated"},
        ])
        out = await Finder(llm).find_for_fact(make_fact(), CANDIDATES)
        assert all(f.state != "CONFIRMED_DRIFT" for f in out)

    @pytest.mark.asyncio
    async def test_nothing_drifted_is_committed_no_drift_not_unknown(self):
        """Having examined the chunks, 'none are wrong' is a decision, not an
        abstention — recording it as UNKNOWN would understate coverage."""
        out = await Finder(ScriptedLLM([])).find_for_fact(make_fact(), CANDIDATES)
        assert len(out) == 1
        assert out[0].state == "NO_DRIFT"

    @pytest.mark.asyncio
    async def test_no_candidates_is_unknown(self):
        cf = make_fact()
        out = await Finder(MockLLMProvider()).find_for_fact(cf, [])
        assert len(out) == 1
        assert out[0].state == "UNKNOWN"
        assert out[0].change_fact_id == str(cf.id)

    @pytest.mark.asyncio
    async def test_llm_failure_abstains_rather_than_guessing(self):
        class Boom(MockLLMProvider):
            async def complete(self, prompt, schema, system=""):
                raise RuntimeError("upstream down")

        out = await Finder(Boom()).find_for_fact(make_fact(), CANDIDATES)
        assert out[0].state == "UNKNOWN"
        assert "failed" in out[0].ai_explanation.lower()

    @pytest.mark.asyncio
    async def test_change_fact_id_is_stamped_on_every_finding(self):
        cf = make_fact()
        llm = ScriptedLLM([
            {"chunk_id": "c1", "drifted": True, "evidence_quote": "run npm install",
             "proposed_old": "npm", "proposed_new": "pnpm", "reason": "x"},
            {"chunk_id": "c2", "drifted": True, "evidence_quote": "run npm test",
             "proposed_old": "npm", "proposed_new": "pnpm", "reason": "x"},
        ])
        out = await Finder(llm).find_for_fact(cf, CANDIDATES)
        assert all(f.change_fact_id == str(cf.id) for f in out)

    @pytest.mark.asyncio
    async def test_falls_back_to_fact_values_when_model_omits_them(self):
        llm = ScriptedLLM([
            {"chunk_id": "c1", "drifted": True, "evidence_quote": "run npm install",
             "reason": "no explicit replacement given"},
        ])
        out = await Finder(llm).find_for_fact(make_fact("npm", "pnpm"), CANDIDATES)
        assert out[0].proposed_old == "npm" and out[0].proposed_new == "pnpm"

    @pytest.mark.asyncio
    async def test_find_batch_returns_a_group_per_fact(self):
        llm = ScriptedLLM([
            {"chunk_id": "c1", "drifted": True, "evidence_quote": "run npm install",
             "proposed_old": "npm", "proposed_new": "pnpm", "reason": "x"},
        ])
        facts = [make_fact(), make_fact("3000", "8080")]
        groups = await Finder(llm).find_batch(facts, [CANDIDATES, CANDIDATES])
        assert len(groups) == 2
        assert all(isinstance(g, list) for g in groups)
