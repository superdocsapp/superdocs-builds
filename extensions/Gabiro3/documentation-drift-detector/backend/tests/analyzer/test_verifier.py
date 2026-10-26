import pytest

from agents.analyzer.finder import FindingOutput
from agents.analyzer.verifier import (
    Verifier,
    normalize,
    quote_appears_in,
    strip_html,
)
from core.llm_provider import MockLLMProvider


class TestQuoteContainment:
    """Whether a quote appears in a chunk is a string comparison, not a
    judgement. The spec is explicit that this proof must be code."""

    CHUNKS = [
        {
            "chunk_id": "c1",
            "html": '<p data-chunk-id="c1">To install dependencies, run '
            "<code>npm install</code>. This downloads packages.</p>",
        }
    ]

    def test_strip_html_removes_tags(self):
        assert strip_html("<p>hello <code>x</code></p>") == "hello x"

    def test_normalize_collapses_whitespace_and_case(self):
        assert normalize("<p>Hello   \n  World</p>") == "hello world"

    def test_finds_quote_spanning_inline_tags(self):
        # The model cites text that crosses a <code> boundary.
        assert quote_appears_in("run npm install", self.CHUNKS)

    def test_finds_quote_with_original_markup(self):
        assert quote_appears_in("run <code>npm install</code>", self.CHUNKS)

    def test_rejects_absent_quote(self):
        assert not quote_appears_in("run pnpm install", self.CHUNKS)

    def test_rejects_empty_quote(self):
        assert not quote_appears_in("", self.CHUNKS)

    def test_rejects_when_no_chunks(self):
        assert not quote_appears_in("anything", [])


class TestVerifierCodeGates:
    """These gates run before any LLM call, so a fabricated quote can never
    reach CONFIRMED regardless of what the model says."""

    @pytest.fixture
    def llm(self):
        return MockLLMProvider()

    def _finding(self, **kw):
        base = dict(
            state="CONFIRMED_DRIFT",
            evidence_quote="run npm install",
            evidence_chunk_id="c1",
            change_fact_id="11111111-1111-1111-1111-111111111111",
            proposed_old="npm install",
            proposed_new="pnpm install",
        )
        base.update(kw)
        return FindingOutput(**base)

    @pytest.mark.asyncio
    async def test_missing_evidence_quote_is_rejected(self, llm):
        out = await Verifier(llm).verify(self._finding(evidence_quote=""), TestQuoteContainment.CHUNKS)
        assert out.state == "UNKNOWN"
        assert "missing evidence" in out.verifier_verdict

    @pytest.mark.asyncio
    async def test_missing_change_fact_id_is_rejected(self, llm):
        out = await Verifier(llm).verify(self._finding(change_fact_id=""), TestQuoteContainment.CHUNKS)
        assert out.state == "UNKNOWN"
        assert "missing evidence" in out.verifier_verdict

    @pytest.mark.asyncio
    async def test_fabricated_quote_is_rejected_before_llm(self, llm):
        out = await Verifier(llm).verify(
            self._finding(evidence_quote="run yarn install"), TestQuoteContainment.CHUNKS
        )
        assert out.state == "UNKNOWN"
        assert "not found" in out.verifier_verdict

    @pytest.mark.asyncio
    async def test_unverified_llm_verdict_downgrades_to_unknown(self, llm):
        # MockLLMProvider returns defaults => verified=False.
        out = await Verifier(llm).verify(self._finding(), TestQuoteContainment.CHUNKS)
        assert out.state == "UNKNOWN"
        assert out.verifier_verdict.startswith("rejected")

    @pytest.mark.asyncio
    async def test_verified_finding_survives(self, llm):
        class Yes(MockLLMProvider):
            async def complete(self, prompt, schema, system=""):
                return schema.model_validate({"verified": True, "reason": "ok"})

        out = await Verifier(Yes()).verify(self._finding(), TestQuoteContainment.CHUNKS)
        assert out.state == "CONFIRMED_DRIFT"
        assert out.verifier_verdict == "verified"

    @pytest.mark.asyncio
    async def test_verifier_failure_falls_to_unknown(self, llm):
        class Boom(MockLLMProvider):
            async def complete(self, prompt, schema, system=""):
                raise RuntimeError("upstream down")

        out = await Verifier(Boom()).verify(self._finding(), TestQuoteContainment.CHUNKS)
        assert out.state == "UNKNOWN"
        assert "failed" in out.verifier_verdict
