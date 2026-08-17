import pytest
from uuid import uuid4
from core.llm_provider import MockLLMProvider


class TestChangeParser:
    @pytest.fixture
    def llm(self):
        return MockLLMProvider()

    @pytest.mark.asyncio
    async def test_parse_renamed_fact(self, llm):
        from agents.analyzer.change_parser import ChangeParser

        cp = ChangeParser(llm)
        feed = [{"type": "renamed", "old_value": "npm", "new_value": "pnpm", "source_ref": "CHANGELOG.md"}]
        import json
        facts = await cp.parse(uuid4(), feed_jsonl=json.dumps(feed))
        assert len(facts) == 1
        assert facts[0].type == "renamed"
        assert facts[0].old_value == "npm"
        assert facts[0].new_value == "pnpm"

    @pytest.mark.asyncio
    async def test_parse_multiple_facts(self, llm):
        from agents.analyzer.change_parser import ChangeParser

        cp = ChangeParser(llm)
        feed = [
            {"type": "renamed", "old_value": "A", "new_value": "B", "source_ref": "R1"},
            {"type": "default_changed", "old_value": "3000", "new_value": "8080", "source_ref": "R2"},
        ]
        import json
        facts = await cp.parse(uuid4(), feed_jsonl=json.dumps(feed))
        assert len(facts) == 2

    @pytest.mark.asyncio
    async def test_parse_preserves_source_ref(self, llm):
        from agents.analyzer.change_parser import ChangeParser

        cp = ChangeParser(llm)
        feed = [{"type": "deprecated", "old_value": "v1", "new_value": None, "source_ref": "SRC-123"}]
        import json
        facts = await cp.parse(uuid4(), feed_jsonl=json.dumps(feed))
        assert facts[0].source_ref == "SRC-123"