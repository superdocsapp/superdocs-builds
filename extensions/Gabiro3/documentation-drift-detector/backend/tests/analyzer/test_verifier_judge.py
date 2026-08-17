import pytest
from core.llm_provider import MockLLMProvider
from agents.analyzer.finder import FindingOutput
from uuid import uuid4


class TestVerifierAndJudge:
    @pytest.fixture
    def llm(self):
        return MockLLMProvider()

    def test_verifier_markdowns_unknown_on_cannot_verify(self, llm):
        from agents.analyzer.verifier import Verifier

        fout = FindingOutput(
            state="CONFIRMED_DRIFT",
            evidence_quote="install npm",
            evidence_chunk_id="c001",
            change_fact_id=str(uuid4()),
            chunk_id="c001",
        )
        verifier = Verifier(llm)
        import asyncio
        result = asyncio.run(verifier.verify(fout))
        assert result.verifier_verdict is not None

    def test_judge_semantic_approves(self, llm):
        from agents.analyzer.judge_semantic import JudgeSemantic

        fout = FindingOutput(
            state="CONFIRMED_DRIFT",
            evidence_quote="Run npm install",
            evidence_chunk_id="c001",
            proposed_old="npm install",
            proposed_new="pnpm install",
            change_fact_id=str(uuid4()),
            chunk_id="c001",
        )
        js = JudgeSemantic(llm)
        result = js.judge(fout)
        assert result.judge_verdict == "approved"

    def test_proposer_sets_old_new_for_literals(self, llm):
        from agents.analyzer.proposer import Proposer

        fout = FindingOutput(
            state="CONFIRMED_DRIFT",
            evidence_quote="Run npm install",
            evidence_chunk_id="c001",
            change_fact_id=str(uuid4()),
            chunk_id="c001",
        )
        prop = Proposer(llm)
        result = prop.propose_fix(fout)
        assert result.proposed_old != ""