import json
from uuid import UUID, uuid4
from core.models import ChangeFact, ChangeFactType
from core.llm_provider import LLMProvider


class ChangeParser:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def parse(self, run_id: UUID, feed_jsonl: str) -> list[ChangeFact]:
        result = []
        items = json.loads(feed_jsonl)
        for item in items:
            cf = ChangeFact(
                id=uuid4(),
                run_id=run_id,
                type=item["type"],
                old_value=item.get("old_value"),
                new_value=item.get("new_value"),
                evidence_span=item.get("evidence_span"),
                source_ref=item.get("source_ref"),
            )
            result.append(cf)
        return result